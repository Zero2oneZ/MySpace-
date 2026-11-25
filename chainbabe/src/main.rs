//! chainbabe CLI - Semantic instruction compiler with dual-model orchestration
//!
//! Usage:
//!   chainbabe submit <instructions>  # Submit instructions for compilation
//!   chainbabe execute <hash>         # Execute a script by hash
//!   chainbabe history [options]      # Show execution history
//!   chainbabe decompile --hash <hash> [--iterations <n>]  # Decompile hash loop

use anyhow::Result;
use clap::Parser;

use chainbabe::{init_and_run, Chainbabe};

/// CLI arguments parser.
#[derive(Parser, Debug)]
#[command(name = "chainbabe")]
#[command(about = "Semantic instruction compiler with dual-model orchestration", long_about = None)]
struct Args {
    /// Project ID for scoping
    #[arg(short, long, default_value = "default")]
    project: String,

    /// Log level (info, warn, debug)
    #[arg(short, long, default_value = "info")]
    log_level: String,

    /// Subcommand
    #[command(subcommand)]
    command: Option<Command>,
}

/// Available subcommands.
#[derive(clap::Subcommand, Debug)]
enum Command {
    /// Submit semantic instructions for compilation
    Submit {
        /// Instructions to compile
        instructions: String,
    },
    /// Execute a script by its hash
    Execute {
        /// Hash of the script to execute
        hash: String,
    },
    /// Show execution history
    History {
        /// Number of entries to show
        #[arg(short, long, default_value = "10")]
        limit: usize,
    },
    /// Decompile hash loop - shows inverted hash iterations
    Decompile {
        /// Initial hash to decompile
        #[arg(long)]
        hash: String,
        /// Number of iterations
        #[arg(long, default_value = "5")]
        iterations: usize,
    },
}

fn main() -> Result<()> {
    let args = Args::parse();

    // Set up logging
    tracing_subscriber::fmt()
        .with_max_level(match args.log_level.as_str() {
            "debug" => tracing::Level::DEBUG,
            "warn" => tracing::Level::WARN,
            _ => tracing::Level::INFO,
        })
        .init();

    match args.command {
        Some(Command::Submit { instructions }) => {
            let chainbabe = Chainbabe::new(&args.project)?;
            let hash = chainbabe.submit(&instructions)?;
            println!("Hash: {}", hash);
        }
        Some(Command::Execute { hash }) => {
            let chainbabe = Chainbabe::new(&args.project)?;
            match chainbabe.execute(&hash) {
                Ok(result) => {
                    println!("Success: {}", result.success);
                    println!("Output:\n{}", result.output);
                    println!("Duration: {}ms", result.duration_ms);
                }
                Err(e) => eprintln!("Error: {}", e),
            }
        }
        Some(Command::History { limit }) => {
            let chainbabe = Chainbabe::new(&args.project)?;
            for entry in chainbabe.history(limit)? {
                let status = entry.status.unwrap_or_else(|| "pending".to_string());
                println!(
                    "[{}] {} -> {} ({}ms)",
                    status,
                    entry.timestamp,
                    entry.result_hash,
                    entry.duration_ms
                );
            }
        }
        Some(Command::Decompile { hash, iterations }) => {
            let chainbabe = Chainbabe::new(&args.project)?;
            println!("=== Hash Loop Decompile ===");
            println!("Starting Hash: {}", hash);
            println!("Iterations: {}", iterations);
            println!("=== Loop (letters ↔ numbers) ===\n");
            let results = chainbabe.orchestrator().hash_loop_decompile(&hash, iterations);
            for content in results.iter() {
                println!("{}\n", content);
            }
            println!("=== End of Loop ===");
        }
        None => {
            init_and_run(&args.project)?;
        }
    }

    Ok(())
}
