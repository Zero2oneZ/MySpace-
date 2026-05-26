# LICENSE — Draft
# IP CONFIDENTIAL — Owner: Tom Lee (Zero2oneZ)
#
# Draft proprietary license. Replace this file with `LICENSE` (no .md,
# no .draft) when text is finalized. Tom should sanity-check the wording
# and optionally have a lawyer review before the first public commit.

---

## Summary in plain English

**This software is NOT open source.** It is the proprietary work of
Tom Lee (Zero2oneZ). The source is published on GitHub so users can
audit the determinism, reproducibility, and scope-discipline claims
made in `README.md` and `ARCHITECTURE.md` — not so they can copy,
redistribute, or commercially exploit the code.

- You **may** read the source.
- You **may** run the code on your own machine for personal evaluation.
- You **may not** redistribute it, fork it as a commercial product,
  resell it, host it for paying users, or incorporate it into a
  commercial product without a written paid license from Tom Lee.
- You **may not** train ML models on this source code.
- The software comes with **no warranty of any kind**.

If you want to use this commercially, **email tom and pay tom.**

---

## Full text (draft — needs review)

```
MySpace++ Proprietary License
Copyright (c) 2026 Tom Lee (Zero2oneZ). All rights reserved.

1. DEFINITIONS

   "Software" means the source code, binaries, configuration, and
   documentation in the MySpace++ repository, in any form or version.

   "You" means any individual or legal entity exercising rights granted
   (or restricted) by this License.

   "Commercial Use" means any use of the Software that is intended for
   or directed toward commercial advantage or monetary compensation,
   including but not limited to: hosting the Software for paying users,
   incorporating the Software into a commercial product or service,
   training machine-learning models on the Software, or using the
   Software inside an organization that generates revenue.

   "Personal Evaluation" means use of the Software by a single natural
   person, on hardware they personally own or control, for the purpose
   of evaluating the Software's behavior, without distributing the
   Software or its output to third parties.

2. PERMISSIONS GRANTED

   Subject to Section 3, You are granted a non-exclusive, non-
   transferable, revocable permission to:

   a. View and read the Software source code.
   b. Run the Software for Personal Evaluation.

3. RESTRICTIONS

   You may NOT, without a separate written commercial license signed
   by the copyright holder:

   a. Redistribute, sublicense, sell, rent, lease, or transfer the
      Software to any third party.
   b. Modify, adapt, translate, or create derivative works of the
      Software for distribution.
   c. Use the Software for any Commercial Use.
   d. Use the Software, in whole or in part, as training data for
      any machine-learning model.
   e. Remove or alter any copyright, license, or attribution notices
      contained in the Software.
   f. Reverse engineer the Software for the purpose of building a
      competing product.

4. NO CONTRIBUTIONS WITHOUT CLA

   Contributions of any kind (code, documentation, configuration) will
   not be accepted into the official Software repository unless the
   contributor first signs a Contributor License Agreement assigning
   copyright in the contribution to the copyright holder. The CLA
   process will be documented separately if and when contributions are
   solicited.

5. COMMERCIAL LICENSING

   For any use not permitted under Section 2, contact the copyright
   holder to negotiate a commercial license:

       Tom Lee (Zero2oneZ)
       <email TBD>

   Pricing and terms are at the copyright holder's sole discretion.

6. NO WARRANTY

   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
   EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
   MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NON-
   INFRINGEMENT. IN NO EVENT SHALL THE COPYRIGHT HOLDER BE LIABLE FOR
   ANY CLAIM, DAMAGES, OR OTHER LIABILITY ARISING FROM, OUT OF, OR IN
   CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
   SOFTWARE.

7. TERMINATION

   This License terminates automatically upon any breach of its terms.
   Upon termination, You must destroy all copies of the Software in
   Your possession or control.

8. GOVERNING LAW

   This License is governed by the laws of <jurisdiction TBD>, without
   regard to its conflict-of-laws provisions.
```

---

## Open items before this becomes `LICENSE`

1. **Email address** for commercial inquiries — pick one and put it
   in §5. Suggest a dedicated alias like `licensing@<domain>` so it
   doesn't get mixed with personal mail.
2. **Jurisdiction** in §8 — likely Massachusetts (Lyv is MA-focused
   per memory), but confirm.
3. **CLA process** in §4 — say "TBD" or actually draft. Recommend
   "TBD; defer until first contributor appears."
4. **Trademark notice** — should `MySpace++` be marked ™? It's not
   registered, but ™ asserts common-law trademark. Add a one-liner.
5. **Lawyer review** — this draft is written by Claude, not a
   lawyer. Recommend a one-hour review with an IP attorney before
   first public commit. Cost: ~$300–500.

---

## Where this license string appears

| Location | Value |
|---|---|
| `LICENSE` (file) | full text above |
| `README.md` header | "**Not Open Source.** Proprietary. See LICENSE." |
| `package.json` | `"license": "SEE LICENSE IN LICENSE"` |
| `pyproject.toml` | `license = { file = "LICENSE" }` + `License-Expression = "LicenseRef-Proprietary"` |
| `Cargo.toml` (if any) | `license-file = "LICENSE"` |
| GitHub repo metadata | License: "Other" (GitHub doesn't recognize this) |
| Docker `LABEL` | `LABEL org.opencontainers.image.licenses="LicenseRef-Proprietary"` |
| `flake.nix` | `meta.license = lib.licenses.unfree;` |

The consistency matters: every package manager that scans for a
license string should see "this is not OSI-approved" without
ambiguity, so nobody accidentally pulls it into an open-source
distribution and gets a takedown email.
