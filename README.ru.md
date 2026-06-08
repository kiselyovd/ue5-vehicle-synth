# ue5-vehicle-synth

[![CI](https://img.shields.io/github/actions/workflow/status/kiselyovd/ue5-vehicle-synth/ci.yml?branch=main&label=CI&style=for-the-badge&logo=github)](https://github.com/kiselyovd/ue5-vehicle-synth/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-mkdocs-526CFE?style=for-the-badge&logo=materialformkdocs&logoColor=white)](https://kiselyovd.github.io/ue5-vehicle-synth/)
[![Coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/kiselyovd/ue5-vehicle-synth/badges/coverage.json&style=for-the-badge&logo=pytest&logoColor=white)](https://github.com/kiselyovd/ue5-vehicle-synth/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge&logo=opensourceinitiative&logoColor=white)](LICENSE)
[![Python 3.13+](https://img.shields.io/badge/Python-3.13%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![HF Hub](https://img.shields.io/badge/🤗%20HF%20Hub-model-FFD21E?style=for-the-badge)](https://huggingface.co/kiselyovd/ue5-vehicle-synth)

UE5-based synthetic vehicle keypoint dataset generation pipeline

**English:** [README.md](README.md)

## Задача

Тип задачи: `keypoints` · Фреймворк: `pytorch`.

## Датасет

Укажите источник датасета, размер, разбиение. Ссылка на Kaggle / HF.

## Результаты

Заполняется после обучения. Таблица метрик: основная модель vs baseline.

| Модель | Метрика 1 | Метрика 2 |
|---|---|---|
| Основная | — | — |
| Baseline | — | — |

## Быстрый старт

```bash
uv sync --all-groups
make data
make train
make evaluate
```

## Структура проекта

```
src/ue5_vehicle_synth/
├── data/
├── models/
├── training/
├── evaluation/
├── inference/
└── utils/
```

## Лицензия

MIT — см. [LICENSE](LICENSE).
