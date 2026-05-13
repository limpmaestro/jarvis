# Recommended Models by VRAM

All models are pulled via `ollama pull <name>`. The Jarvis Modelfile
defaults to `qwen2.5:14b-instruct-q4_K_M`. Change `FROM` in
`models/Jarvis.Modelfile` and rebuild with `ollama create jarvis -f ...`.

## LLM (chat / reasoning / tool use)

| VRAM     | Model                              | Size  | Notes                         |
|----------|------------------------------------|-------|-------------------------------|
| ≥ 24 GB  | `qwen2.5:32b-instruct-q4_K_M`     | ~20 GB| Best quality, great tool use  |
| ≥ 12 GB  | `qwen2.5:14b-instruct-q4_K_M`     | ~9 GB | **Default**. Strong all-round |
| ≥ 8 GB   | `qwen2.5:7b-instruct-q4_K_M`      | ~5 GB | Fast, good for most tasks     |
| ≥ 6 GB   | `phi3:mini-4k-instruct`            | ~3.8 GB| Smaller but capable          |
| ≤ 4 GB   | `qwen2.5:3b-instruct-q4_K_M`      | ~2 GB | Lightweight, limited tools    |

## Embedding (memory)

| Model                    | Dims | Notes                             |
|--------------------------|------|-----------------------------------|
| `nomic-embed-text:v1.5`  | 768  | **Default**. Multilingual, fast   |
| `mxbai-embed-large`      | 1024 | Better English, larger           |

## STT (faster-whisper)

| VRAM     | Model          | Notes                              |
|----------|----------------|------------------------------------|
| ≥ 10 GB  | `large-v3-turbo` | **Default**. Best accuracy       |
| ≥ 6 GB   | `medium`       | Good accuracy, lower VRAM          |
| CPU only | `small`        | Acceptable, ~1.5× real-time       |

STT runs concurrently with the LLM; plan VRAM accordingly.
