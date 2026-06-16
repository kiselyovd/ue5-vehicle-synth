# ue5-vehicle-synth

[![CI](https://img.shields.io/github/actions/workflow/status/kiselyovd/ue5-vehicle-synth/ci.yml?branch=main&label=CI&style=for-the-badge&logo=github)](https://github.com/kiselyovd/ue5-vehicle-synth/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-mkdocs-526CFE?style=for-the-badge&logo=materialformkdocs&logoColor=white)](https://kiselyovd.github.io/ue5-vehicle-synth/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge&logo=opensourceinitiative&logoColor=white)](LICENSE)
[![Python 3.13+](https://img.shields.io/badge/Python-3.13%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![UE 5.6](https://img.shields.io/badge/Unreal_Engine-5.6-0E1128?style=for-the-badge&logo=unrealengine&logoColor=white)](https://www.unrealengine.com/)

Пайплайн генерации синтетического датасета ключевых точек автомобилей на Unreal Engine 5 и Epic City Sample. Ставит машины на реальную дорожную сеть, рендерит фотореалистичные кадры через Movie Render Queue и экспортирует COCO-аннотации ключевых точек для обучения модели [`vehicle-keypoints`](https://github.com/kiselyovd/vehicle-keypoints).

**English version:** [README.md](README.md)

![Фотореалистичный кадр City Sample, отрендеренный через Movie Render Queue](docs/images/hero_render.png)

## Зачем

Реальные данные по ключевым точкам автомобилей дефицитны и дороги в разметке. Симулятор даёт идеальные, бесплатные, пиксельно точные аннотации и неограниченное разнообразие ракурсов, машин, погоды и времени суток. Этот проект строит генератор как переиспользуемый C++ плагин Unreal Engine (`UESynthCapture`) и использует его, чтобы расширить `vehicle-keypoints` с 14-точечной до 24-точечной схемы по рецепту sim-to-real.

Нарратив намеренно конкретный: кадры рендерятся внутри City Sample ("Matrix Awakens") от Epic, поэтому датасет несёт узнаваемый высококачественный вид и при этом полностью пригоден к распространению (см. [Правовой статус](#правовой-статус)).

## Как это работает

Пайплайн разделяет аннотацию (быстро, в редакторе) и рендер (gold-path, оффлайн):

1. **Определение дороги.** C++ обёртка (`USynthRoadQuery`) читает запечённую сеть полос ZoneGraph City Sample напрямую из движка и возвращает позиции полос плюс направления движения. Риг-машина ставится на реальную полосу, выравнивается по направлению трафика. Запасной путь - трассировка дорожной поверхности, когда данных ZoneGraph нет.

   ![Сеть дорог, определённая из ZoneGraph](docs/images/zonegraph_lanes.png)

2. **Проекция ключевых точек.** Для каждой позы камеры компонент `USynthVehicleAnnotator` проецирует 24 анатомические точки в пиксели и выполняет двунаправленную трассировку перекрытий, назначая видимость в стиле CarFusion (`v=2` видна, `v=1` самоперекрыта, `v=0` вне кадра). Bounding box строится по границам меша машины, поэтому доходит до низа колёс как в реальных аннотациях. Размечаются все видимые городские машины в кадре, а не только риг.

3. **Gold-path рендер.** Keyframed Level Sequence проводит одну камеру через все позы; Movie Render Queue рендерит каждую как резкий кадр 1280x720 с полным Lumen GI и трассировкой лучей (motion blur отключён для чётких стиллов).

   ![Три позы из одной keyframed-секвенции Movie Render Queue](docs/images/multipose.png)

4. **Экспорт.** Покадровый JSONL конвертируется в валидированный multi-instance COCO-датасет ключевых точек, который затем потребляет пайплайн обучения `vehicle-keypoints`.

### Ключевые точки на реальной машине

Каждая машина размечается полной 24-точечной схемой плюс bounding box по границам меша, доходящий до низа колёс как ручная разметка. Точки раскрашены по видимости (зелёная - видна, жёлтая - самоперекрыта), а проекция откалибрована против реального рендера, чтобы метки ложились на пиксели:

![24 ключевые точки и bounding box, спроецированные на машину City Sample](docs/images/calibration.png)

## 24-точечная схема

Первые 14 точек - канонический порядок CarFusion (колёса, фары и габариты, углы крыши, центр, выхлоп) для обратной совместимости с моделью v1. Десять новых точек (боковые зеркала, углы бамперов, углы оснований окон) расширяют схему. Якоря точек заданы по типу машины в `configs/vehicles/`.

## Статус

Phase 0 vertical slice. Пайплайн захвата, C++ плагин, постановка на дорогу через ZoneGraph, gold-path рендер и драйвер sim-to-real обучения собраны и провалидированы end-to-end. Текущий фокус - kill switch Phase 0 (синтетическое предобучение должно поднять OKS-mAP модели v1 минимум на +2pp на тесте CarFusion); результаты и релиз полного датасета будут задокументированы здесь по мере готовности. Инженерный разбор - в [Wiki](wiki/Home.md).

## Стек

Unreal Engine 5.6 + City Sample, C++ плагин захвата (`UESynthCapture`), Python в редакторе через UnrealMCP, Movie Render Queue, Python 3.13 с uv / ruff / pytest, и ultralytics YOLO-pose на стороне обучения.

## Быстрый старт (Python-часть)

```bash
uv sync --all-groups
uv run pytest
```

Часть захвата в Unreal требует UE 5.6 и проекта City Sample; см. [Wiki](wiki/Home.md) для рабочего процесса захвата.

## Правовой статус

Кадры рендерятся из City Sample от Epic. По EULA Unreal Engine неинтерактивные медиа (изображения), отрендеренные движком, свободно распространяемы; не распространяются только сами файлы ассетов UE-Only-Content. Этот датасет шипит только отрендеренные PNG-кадры и JSON-аннотации, никогда не файлы ассетов Epic, поэтому остаётся в рамках лицензии. Полный разбор: [docs/legal/CITY_SAMPLE_EULA_REVIEW.md](docs/legal/CITY_SAMPLE_EULA_REVIEW.md).

## Лицензия

MIT - см. [LICENSE](LICENSE). Лицензия MIT покрывает код этого репозитория и производимые им кадры / аннотации, но не базовые ассеты Epic.
