"""QLoRA fine-tune of a local model on the lessons from `yellow-teach`, exported for Ollama.

Runs in the training venv (Python 3.12, PyTorch + Unsloth), not the game's venv, and imports
nothing from the package: lessons come in as JSONL. Run it under the GPU guard::

    .venv/bin/yellow-gpu-guard --vram-limit 15000 -- \\
        .venv-train/bin/python src/yellow_agent/tools/train_lora.py \\
        --lessons data/generated/teach --out data/generated/lora-qwen3-8b

Then `ollama create qwen3-8b-yellow -f <out>/Modelfile`.

Choices: 4-bit base (fits the 16 GB card with room), LoRA r=16 on all projections, loss only on
the assistant's tool call (the prompt is the game state: nothing to learn there), thinking off
in the chat template (Ollama runs it with think=false).
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


def load_rows(lessons: Path) -> tuple[list[dict], list[dict]]:
    rows = [json.loads(line) for line in (lessons / "train.jsonl").read_text().splitlines()]
    tools = json.loads((lessons / "tools.json").read_text())
    return rows, tools


def to_text(row: dict, tools: list[dict], tokenizer) -> str:
    messages = []
    for m in row["messages"]:
        m = dict(m)
        if m.get("tool_calls"):  # chat templates expect arguments as a dict
            m["tool_calls"] = [
                {"type": "function", "function": dict(tc["function"])} for tc in m["tool_calls"]
            ]
        messages.append(m)
    return tokenizer.apply_chat_template(
        messages, tools=tools, tokenize=False, add_generation_prompt=False, enable_thinking=False
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="QLoRA fine-tune on yellow-teach lessons.")
    parser.add_argument("--lessons", type=Path, default=Path("data/generated/teach"))
    parser.add_argument("--out", type=Path, default=Path("data/generated/lora-qwen3-8b"))
    parser.add_argument("--base", default="unsloth/Qwen3-8B-unsloth-bnb-4bit")
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--max-len", type=int, default=4096)
    parser.add_argument("--eval-share", type=float, default=0.05)
    parser.add_argument("--quant", default="q4_k_m")
    args = parser.parse_args()

    from unsloth import FastLanguageModel  # noqa: I001 - first: it patches transformers
    from unsloth.chat_templates import train_on_responses_only

    import torch
    from datasets import Dataset
    from trl import SFTConfig, SFTTrainer

    rows, tools = load_rows(args.lessons)
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.base, max_seq_length=args.max_len, load_in_4bit=True
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=args.rank,
        lora_alpha=args.rank,
        lora_dropout=0,
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
        use_gradient_checkpointing="unsloth",
        random_state=7,
    )
    texts = [to_text(r, tools, tokenizer) for r in rows]
    lengths = [len(tokenizer(t).input_ids) for t in texts]
    keep = [t for t, n in zip(texts, lengths, strict=True) if n <= args.max_len]
    random.Random(7).shuffle(keep)
    n_eval = max(1, int(len(keep) * args.eval_share))
    train, evals = (
        Dataset.from_dict({"text": keep[n_eval:]}),
        Dataset.from_dict({"text": keep[:n_eval]}),
    )
    print(f"lessons {len(rows)}, kept {len(keep)} (<= {args.max_len} tokens), "
          f"longest {max(lengths)}, train {len(train)}, eval {len(evals)}")  # fmt: skip

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train,
        eval_dataset=evals,
        args=SFTConfig(
            dataset_text_field="text",
            max_seq_length=args.max_len,
            per_device_train_batch_size=2,
            gradient_accumulation_steps=4,
            num_train_epochs=args.epochs,
            learning_rate=args.lr,
            lr_scheduler_type="cosine",
            warmup_ratio=0.05,
            logging_steps=5,
            eval_strategy="epoch",
            save_strategy="no",
            optim="adamw_8bit",
            bf16=torch.cuda.is_bf16_supported(),
            fp16=not torch.cuda.is_bf16_supported(),
            seed=7,
            report_to="none",
            output_dir=str(args.out / "checkpoints"),
        ),
    )
    trainer = train_on_responses_only(
        trainer,
        instruction_part="<|im_start|>user\n",
        response_part="<|im_start|>assistant\n",
    )
    stats = trainer.train()
    metrics = trainer.evaluate()
    args.out.mkdir(parents=True, exist_ok=True)
    summary = {
        "base": args.base, "lessons": len(rows), "train": len(train), "eval": len(evals),
        "epochs": args.epochs, "lr": args.lr, "rank": args.rank, "max_len": args.max_len,
        "train_loss": stats.training_loss, "eval_loss": metrics.get("eval_loss"),
        "train_runtime_s": stats.metrics.get("train_runtime"),
        "log": [e for e in trainer.state.log_history if "loss" in e or "eval_loss" in e],
    }  # fmt: skip
    (args.out / "train_summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "log"}))

    model.save_pretrained(str(args.out / "adapter"))
    tokenizer.save_pretrained(str(args.out / "adapter"))
    model.save_pretrained_gguf(str(args.out / "gguf"), tokenizer, quantization_method=args.quant)
    gguf = sorted((args.out / "gguf").glob("*.gguf"))
    if not gguf:
        gguf = sorted(args.out.glob("*.gguf"))
    print("gguf:", [str(g) for g in gguf])


if __name__ == "__main__":
    main()
