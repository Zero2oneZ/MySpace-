#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        sentence_chain
# role:        SUBSTRATE · FREE_SYNTACTIC_EMBEDDING_AXIS
# tier:        L0
# substrate:   per-sentence 96-dim float vector (pure Python, no LLM)
# engine:      old-school NLP heuristics + chain-context modulation
# storage:     none (stateless transform — embeddings live on the caller's records)
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.sentence_chain.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - inference_logger (planned — every record gets per-sentence embeddings)
#   - moe_router.find_sentence_neighbors (when wired — 4th retrieval axis)
#   - workflow_generator (planned — describe surface comments via skeleton hashes)
# outbound:
#   - blake3 (or blake2b fallback) — skeleton hashing
#   - stdlib only: re, math, string, collections (no ML, no third-party NLP)
# determinism:
#   - same sentence + same prior chain → same 96-d vector, bytes-exact
# free axis:
#   - zero LLM calls, zero model loads, zero training cost
#   - the FOURTH MoE retrieval axis alongside vector / wave / time
# ============================================================================
"""sentence_chain.py — free syntactic embedding using old-school Python NLP.

The 96-dim layout:
  [ 0:16] — surface stats   (length, word count, avg word len, cap rate, etc.)
  [16:48] — n-gram buckets  (32 hashed word-bigram counts)
  [48:64] — skeleton buckets(16 hashed content-word presence flags)
  [64:80] — POS histogram   (16 buckets — noun/verb/pron/prep/conj/det/aux/adj/...)
  [80:96] — chain context   (position, shared-words-with-prior, conjunction-cont, etc.)

Final vector is L2-normalized → cosine similarity = dot product.

Old-school tricks used (no ML, no training):
  * Sentence boundary via regex: (?<=[.!?])\\s+(?=[A-Z])
  * Stop-word filtering using a hand-curated ~100-word set
  * POS proxy via suffix matching (-ing/-ed/-tion/-ment/-ity/-ly/...)
  * Subject-Verb-Object guesses via state-machine over tokens
  * Skeleton = content words sorted + blake3 → 16 buckets
  * N-grams via blake2b → 32 buckets (Counting Bloom-ish)
  * Chain context: shared content words with prior sentences (Markov-ish bias)
"""
from __future__ import annotations

import hashlib
import math
import re
import string
from collections import Counter
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple


try:
    import blake3 as _blake3_mod
    def _hash(data: bytes) -> str:
        return _blake3_mod.blake3(data).hexdigest()
except ImportError:
    def _hash(data: bytes) -> str:
        return hashlib.blake2b(data).hexdigest()


EMB_DIM = 96
NGRAM_BUCKETS = 32
SKELETON_BUCKETS = 16
POS_BUCKETS = 16


# ---------------------------------------------------------------------------
# Closed-class word lists (hand-curated)
# ---------------------------------------------------------------------------

STOP_WORDS = frozenset("""
a an the and or but if while when where why how what which who whom whose
in on at to from by of for with about against between into through during
before after above below up down out off over under again further then once
is am are was were be been being do does did doing have has had having
i you he she it we they me him her us them my your his its our their
this that these those there here
will would shall should can could may might must
not no nor as so than too very just only own same such own
""".split())

PRONOUNS = frozenset("i you he she it we they me him her us them my your his its our their this that these those there here someone something anyone anything everyone everything".split())
PREPOSITIONS = frozenset("in on at to from by of for with about against between into through during before after above below up down out off over under into onto upon".split())
CONJUNCTIONS = frozenset("and or but yet so nor because although though if when while since unless until whereas".split())
DETERMINERS = frozenset("a an the this that these those my your his her its our their some any all each every".split())
AUX_VERBS = frozenset("is am are was were be been being do does did doing have has had having will would shall should can could may might must".split())
QUESTION_WORDS = frozenset("what when where why how who whom whose which".split())
NEGATIONS = frozenset("not never no none n't nothing nobody nowhere neither nor".split())

# Suffix tables — Porter-style heuristics
VERB_SUFFIXES = ("ing", "ed", "en", "ize", "ise", "ify", "ate", "ze", "se")
NOUN_SUFFIXES = ("tion", "sion", "ment", "ness", "ity", "ence", "ance", "ship", "hood", "dom",
                  "ist", "ism", "er", "or", "age", "cy")
ADJ_SUFFIXES = ("ous", "ful", "less", "able", "ible", "ive", "ial", "ic", "al",
                "ant", "ent", "ish", "y", "ar", "ary")
ADV_SUFFIXES = ("ly", "ward", "wise")


SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'])")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_'-]*")
PUNCT_RE = re.compile(f"[{re.escape(string.punctuation)}]")


# ---------------------------------------------------------------------------
# Sentence splitting
# ---------------------------------------------------------------------------

def split_sentences(text: str) -> List[str]:
    """Pure-regex sentence boundary detection. Robust for common cases;
    will miss the long-tail (abbreviations, e.g., 'Dr.', 'etc.')."""
    if not text:
        return []
    parts = SENT_SPLIT_RE.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


def tokenize(sentence: str) -> List[str]:
    return WORD_RE.findall(sentence.lower())


# ---------------------------------------------------------------------------
# Suffix-based POS proxies
# ---------------------------------------------------------------------------

def pos_class(token: str) -> str:
    """Return one of: noun / verb / pronoun / preposition / conjunction /
    determiner / aux / adj / adv / other."""
    t = token.lower()
    if t in PRONOUNS:      return "pronoun"
    if t in PREPOSITIONS:  return "preposition"
    if t in CONJUNCTIONS:  return "conjunction"
    if t in DETERMINERS:   return "determiner"
    if t in AUX_VERBS:     return "aux"
    if any(t.endswith(s) for s in ADV_SUFFIXES) and len(t) > 4:
        return "adv"
    if any(t.endswith(s) for s in NOUN_SUFFIXES) and len(t) > 5:
        return "noun"
    if any(t.endswith(s) for s in VERB_SUFFIXES) and len(t) > 4:
        return "verb"
    if any(t.endswith(s) for s in ADJ_SUFFIXES) and len(t) > 4:
        return "adj"
    return "other"


# ---------------------------------------------------------------------------
# Sentence feature extraction
# ---------------------------------------------------------------------------

@dataclass
class SentenceFeatures:
    sentence: str
    tokens: List[str]
    word_count: int
    char_count: int
    avg_word_len: float
    cap_rate: float
    punct_density: float
    is_question: bool
    is_negated: bool
    is_imperative: bool
    starts_with_conjunction: bool
    stop_word_count: int
    content_words: List[str]
    pos_histogram: Dict[str, int]
    skeleton: str            # sorted content words joined
    subject_guess: str
    verb_guess: str
    object_guess: str
    position_in_turn: int = 0


def featurize(sentence: str, position: int = 0) -> SentenceFeatures:
    raw = sentence.strip()
    tokens = tokenize(raw)
    word_count = len(tokens)
    char_count = len(raw)
    avg_word_len = (sum(len(t) for t in tokens) / word_count) if word_count else 0.0

    # Cap rate (uppercase letters in raw text) and punctuation density
    cap_chars = sum(1 for c in raw if c.isupper())
    cap_rate = (cap_chars / char_count) if char_count else 0.0
    punct_count = len(PUNCT_RE.findall(raw))
    punct_density = (punct_count / char_count) if char_count else 0.0

    is_question = bool(raw.endswith("?")) or (bool(tokens) and tokens[0] in QUESTION_WORDS)
    is_negated = any(t in NEGATIONS for t in tokens) or "n't" in raw.lower()
    starts_with_conjunction = bool(tokens) and tokens[0] in CONJUNCTIONS

    # POS histogram
    pos_hist: Counter = Counter()
    for t in tokens:
        pos_hist[pos_class(t)] += 1

    # Imperative: starts with a verb (by suffix), not a pronoun/determiner, not a question
    is_imperative = (
        bool(tokens)
        and pos_class(tokens[0]) in ("verb", "aux")
        and tokens[0] not in PRONOUNS and tokens[0] not in DETERMINERS
        and not is_question
    )

    stop_word_count = sum(1 for t in tokens if t in STOP_WORDS)
    content_words = [t for t in tokens if t not in STOP_WORDS and len(t) > 2]
    skeleton = " ".join(sorted(set(content_words)))

    # Subj/Verb/Obj guess via state machine
    subject_guess, verb_guess, object_guess = _svo_guess(tokens)

    return SentenceFeatures(
        sentence=raw,
        tokens=tokens,
        word_count=word_count,
        char_count=char_count,
        avg_word_len=avg_word_len,
        cap_rate=cap_rate,
        punct_density=punct_density,
        is_question=is_question,
        is_negated=is_negated,
        is_imperative=is_imperative,
        starts_with_conjunction=starts_with_conjunction,
        stop_word_count=stop_word_count,
        content_words=content_words,
        pos_histogram=dict(pos_hist),
        skeleton=skeleton,
        subject_guess=subject_guess,
        verb_guess=verb_guess,
        object_guess=object_guess,
        position_in_turn=position,
    )


def _svo_guess(tokens: List[str]) -> Tuple[str, str, str]:
    """Tiny state machine: looking_for_subject → looking_for_verb → looking_for_object."""
    if not tokens:
        return ("", "", "")
    state = "subj"
    subj = verb = obj = ""
    for t in tokens:
        cls = pos_class(t)
        if state == "subj":
            if cls in ("pronoun", "noun") or (cls == "other" and t not in STOP_WORDS and t not in DETERMINERS):
                subj = t
                state = "verb"
        elif state == "verb":
            if cls in ("verb", "aux"):
                verb = t
                state = "obj"
        elif state == "obj":
            if cls in ("noun", "pronoun") or (cls == "other" and t not in STOP_WORDS):
                obj = t
                break
    return subj, verb, obj


# ---------------------------------------------------------------------------
# Embedding builder — 96-dim L2-normalized float vector
# ---------------------------------------------------------------------------

def _hash_to_bucket(token: str, buckets: int, salt: str = "") -> int:
    h = hashlib.blake2b((salt + "|" + token).encode("utf-8"), digest_size=4).digest()
    return int.from_bytes(h, "big") % buckets


def _ngram_buckets(tokens: List[str], n: int = 2, num_buckets: int = NGRAM_BUCKETS) -> List[float]:
    counts = [0.0] * num_buckets
    if len(tokens) < n:
        return counts
    for i in range(len(tokens) - n + 1):
        g = "_".join(tokens[i : i + n])
        counts[_hash_to_bucket(g, num_buckets, "ngram")] += 1.0
    return counts


def _skeleton_buckets(content_words: List[str], num_buckets: int = SKELETON_BUCKETS) -> List[float]:
    flags = [0.0] * num_buckets
    for w in set(content_words):
        flags[_hash_to_bucket(w, num_buckets, "skel")] = 1.0
    return flags


_POS_KEYS = ("noun", "verb", "pronoun", "preposition", "conjunction",
             "determiner", "aux", "adj", "adv", "other")


def _pos_histogram_vec(pos_hist: Dict[str, int], n_words: int) -> List[float]:
    vec = [0.0] * POS_BUCKETS
    if n_words == 0:
        return vec
    for i, k in enumerate(_POS_KEYS):
        if i < POS_BUCKETS:
            vec[i] = pos_hist.get(k, 0) / n_words
    return vec


def _chain_context_vec(features: SentenceFeatures,
                       prior_features: Optional[List["SentenceFeatures"]] = None) -> List[float]:
    """Last 16 dims — positional + chain-conditional bias."""
    vec = [0.0] * 16
    vec[0] = float(features.position_in_turn)
    vec[1] = 1.0 if features.starts_with_conjunction else 0.0
    vec[2] = 1.0 if features.is_question else 0.0
    vec[3] = 1.0 if features.is_negated else 0.0
    vec[4] = 1.0 if features.is_imperative else 0.0

    if prior_features:
        my_set = set(features.content_words)
        # 5: shared content words with the immediate prior sentence
        prev = prior_features[-1]
        shared = len(my_set & set(prev.content_words))
        vec[5] = shared / max(1, len(my_set))
        # 6: shared with any prior in the chain
        all_prior = set()
        for p in prior_features:
            all_prior.update(p.content_words)
        vec[6] = len(my_set & all_prior) / max(1, len(my_set))
        # 7: avg word-length delta from prior
        vec[7] = features.avg_word_len - prev.avg_word_len
        # 8: subject continuity (same as prior subject?)
        vec[8] = 1.0 if (features.subject_guess and features.subject_guess == prev.subject_guess) else 0.0

    # 9-15 spare for future chain features
    return vec


def _l2_normalize(vec: List[float]) -> List[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm < 1e-12:
        return vec
    return [x / norm for x in vec]


def sentence_embedding(sentence: str,
                       position: int = 0,
                       prior_features: Optional[List[SentenceFeatures]] = None) -> List[float]:
    f = featurize(sentence, position)
    vec: List[float] = []

    # [0:16] surface stats
    surface = [0.0] * 16
    surface[0] = math.log1p(f.word_count) / 5.0
    surface[1] = math.log1p(f.char_count) / 6.0
    surface[2] = f.avg_word_len / 10.0
    surface[3] = f.cap_rate
    surface[4] = f.punct_density
    surface[5] = (f.stop_word_count / f.word_count) if f.word_count else 0.0
    surface[6] = (len(f.content_words) / f.word_count) if f.word_count else 0.0
    surface[7] = 1.0 if f.is_question else 0.0
    surface[8] = 1.0 if f.is_negated else 0.0
    surface[9] = 1.0 if f.is_imperative else 0.0
    surface[10] = 1.0 if f.starts_with_conjunction else 0.0
    surface[11] = float(bool(f.subject_guess))
    surface[12] = float(bool(f.verb_guess))
    surface[13] = float(bool(f.object_guess))
    surface[14] = 1.0 if f.sentence.endswith("?") else 0.0
    surface[15] = 1.0 if f.sentence.endswith("!") else 0.0
    vec.extend(surface)

    # [16:48] ngram buckets — normalized counts
    ng = _ngram_buckets(f.tokens, n=2, num_buckets=NGRAM_BUCKETS)
    total_ng = sum(ng)
    if total_ng > 0:
        ng = [x / total_ng for x in ng]
    vec.extend(ng)

    # [48:64] skeleton buckets — binary presence
    vec.extend(_skeleton_buckets(f.content_words, num_buckets=SKELETON_BUCKETS))

    # [64:80] POS histogram (normalized)
    vec.extend(_pos_histogram_vec(f.pos_histogram, f.word_count))

    # [80:96] chain context
    vec.extend(_chain_context_vec(f, prior_features))

    # Pad / trim to EMB_DIM
    if len(vec) < EMB_DIM:
        vec.extend([0.0] * (EMB_DIM - len(vec)))
    elif len(vec) > EMB_DIM:
        vec = vec[:EMB_DIM]

    return _l2_normalize(vec)


# ---------------------------------------------------------------------------
# Chain-level embedder: turn an entire turn / text into a list of (features, emb, crystal)
# ---------------------------------------------------------------------------

@dataclass
class SentenceNode:
    sentence: str
    position: int
    features: SentenceFeatures
    embedding: List[float]
    skeleton_hash: str
    crystal: str


def embed_chain(text: str) -> List[SentenceNode]:
    """Split text into sentences, embed each with chain-context modulation
    (each sentence sees the prior ones). Returns a list of SentenceNodes."""
    sentences = split_sentences(text)
    prior_features: List[SentenceFeatures] = []
    nodes: List[SentenceNode] = []
    for i, s in enumerate(sentences):
        feats = featurize(s, position=i)
        emb = sentence_embedding(s, position=i, prior_features=prior_features)
        skeleton_hash = _hash(feats.skeleton.encode("utf-8"))[:16]
        # Crystal: blake3 over (skeleton + position + content_words)
        canonical = f"{i}|{feats.skeleton}|{','.join(feats.tokens)}".encode("utf-8")
        crystal = _hash(canonical)
        nodes.append(SentenceNode(
            sentence=s,
            position=i,
            features=feats,
            embedding=emb,
            skeleton_hash=skeleton_hash,
            crystal=crystal,
        ))
        prior_features.append(feats)
    return nodes


# ---------------------------------------------------------------------------
# Retrieval — find similar sentences across an indexed corpus
# ---------------------------------------------------------------------------

def cosine_similarity(a: List[float], b: List[float]) -> float:
    if len(a) != len(b):
        n = min(len(a), len(b))
        a = a[:n]; b = b[:n]
    return sum(x * y for x, y in zip(a, b))


def find_sentence_neighbors(query: str,
                            corpus: List[Dict[str, Any]],
                            k: int = 5,
                            min_sim: float = 0.0) -> List[Dict[str, Any]]:
    """Each corpus entry: {"sentence": str, "embedding": List[float], **meta}.
    Returns top-k by cosine similarity over the syntactic embedding."""
    q_emb = sentence_embedding(query)
    scored = []
    for item in corpus:
        emb = item.get("embedding") or []
        if not emb:
            continue
        sim = cosine_similarity(q_emb, emb)
        if sim < min_sim:
            continue
        scored.append({**{k: v for k, v in item.items() if k != "embedding"},
                       "sentence_sim": round(sim, 6)})
    scored.sort(key=lambda x: -x["sentence_sim"])
    return scored[:k]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _compact_node(n: SentenceNode, emb_show: int = 10) -> Dict[str, Any]:
    return {
        "sentence": n.sentence,
        "position": n.position,
        "skeleton": n.features.skeleton[:80],
        "skeleton_hash": n.skeleton_hash,
        "crystal": n.crystal[:16],
        "svo": [n.features.subject_guess, n.features.verb_guess, n.features.object_guess],
        "pos_histogram": n.features.pos_histogram,
        "is_question": n.features.is_question,
        "is_imperative": n.features.is_imperative,
        "is_negated": n.features.is_negated,
        "embedding_head": [round(x, 5) for x in n.embedding[:emb_show]],
    }


def _main():
    import argparse, json, sys
    ap = argparse.ArgumentParser(description="sentence_chain — free syntactic embedding axis")
    sub = ap.add_subparsers(dest="cmd")

    p_emb = sub.add_parser("embed", help="embed one or more sentences")
    p_emb.add_argument("text", help="text (or '-' to read stdin)")
    p_emb.add_argument("--full", action="store_true")

    p_cmp = sub.add_parser("compare", help="compare two strings on the syntactic axis")
    p_cmp.add_argument("a"); p_cmp.add_argument("b")

    p_pos = sub.add_parser("pos", help="show POS proxies for a string")
    p_pos.add_argument("text")

    p_find = sub.add_parser("find", help="find nearest sentences in a JSONL corpus")
    p_find.add_argument("query")
    p_find.add_argument("corpus_path", help="JSONL with one {sentence,embedding,...} per line")
    p_find.add_argument("-k", type=int, default=5)

    args = ap.parse_args()

    if args.cmd == "embed":
        text = sys.stdin.read() if args.text == "-" else args.text
        nodes = embed_chain(text)
        if args.full:
            print(json.dumps([asdict(n) for n in nodes], indent=2, default=lambda o: list(o) if hasattr(o, "__iter__") else str(o)))
        else:
            print(json.dumps([_compact_node(n) for n in nodes], indent=2))

    elif args.cmd == "compare":
        ea = sentence_embedding(args.a)
        eb = sentence_embedding(args.b)
        fa = featurize(args.a); fb = featurize(args.b)
        print(json.dumps({
            "a_svo": [fa.subject_guess, fa.verb_guess, fa.object_guess],
            "b_svo": [fb.subject_guess, fb.verb_guess, fb.object_guess],
            "cosine_sim": round(cosine_similarity(ea, eb), 6),
            "a_skeleton": fa.skeleton,
            "b_skeleton": fb.skeleton,
        }, indent=2))

    elif args.cmd == "pos":
        toks = tokenize(args.text)
        print(json.dumps([{"token": t, "pos": pos_class(t)} for t in toks], indent=2))

    elif args.cmd == "find":
        corpus = []
        with open(args.corpus_path) as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try:
                    corpus.append(json.loads(line))
                except Exception:
                    pass
        matches = find_sentence_neighbors(args.query, corpus, k=args.k)
        print(json.dumps(matches, indent=2))

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
