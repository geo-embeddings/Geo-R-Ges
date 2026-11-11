# Selection guide

Rules of thumb for turning a use case into model choices. Verify anything time-sensitive
(product years, sensor status) against the source before relying on it.

## Compute tiers

| User says | Means | Suitable |
|---|---|---|
| "no compute", "just a laptop", "no GPU" | no model inference beyond a small classifier | precomputed embedding products (`--embeddings-only`); tiny pixel/time-series encoders (< ~5M params, e.g. run on CPU) |
| "a laptop GPU", "Colab" | single small GPU, inference + light fine-tuning | encoders up to ~100M params (ViT-S/B); frozen features + linear probe for larger |
| "one good GPU" | full fine-tuning of base models | up to ~300-600M params |
| "a cluster" | anything | any, including large VLMs |

With little compute and few labels, frozen embeddings + a simple classifier (random
forest, logistic regression, k-NN) is the usual starting point and often competitive.
Cost also scales with area x dates: a tiny model over a whole country of time series
can cost more than downloading precomputed embeddings.

## Embedding products

- Coverage is per published year/layer. The record's `end_datetime` may lag the
  product; check the product page for the latest layer and for planned releases.
- Annual products are calendar-year summaries. Southern-hemisphere summer crops
  (e.g. South Africa's maize/soy, planted roughly Oct-Dec, harvested Apr-Jun) span two
  calendar years, so one annual layer may mix two seasons; winter crops (e.g. Western
  Cape wheat, roughly May-Nov) fit one calendar year. For in-season monitoring
  (progress within the season, not end-of-season maps) annual embeddings do not help;
  use a time-series encoder on current imagery.
- Access matters: Earth Engine collections need an EE account (free for
  non-commercial/research); others are downloads (Source Cooperative, Hugging Face,
  project tools). Check the license for commercial use.

## Data and period

- Model pretraining years matter less than input compatibility: a model pretrained on
  2017-2023 Sentinel-2 usually transfers to 2025 imagery, given the same processing.
- Sentinel-2 L2A from processing baseline 04.00 (January 2022) carries a -1000 offset
  (`BOA_ADD_OFFSET`); models pretrained on older L2A need it removed or harmonised.
  Check whether a model expects L1C (TOA) or L2A (BOA).
- Sensor availability: Sentinel-1B stopped in December 2021 (lower S1 revisit until
  Sentinel-1C, launched December 2024); Landsat 7 is retired. A model that needs a sensor
  without data in the requested period is unusable without substitution.
- Cloudy regions or seasons favour SAR-capable or multi-sensor models.

## Resolution vs object size

- 10 m (Sentinel-2) resolves fields of roughly >= 0.5-1 ha; large commercial fields are
  fine, very small smallholder plots (< ~0.5 ha) blur. Then prefer VHR-capable models,
  or parcel-level aggregation of pixel embeddings, and say the limitation.
- Pixel time-series models (Presto-like) give per-pixel outputs; patch ViTs give
  per-patch features that need a decoder for maps.

## Weighing benchmark evidence

Strongest to weakest: same task + same region; same task + similar region (continent,
climate, farming system); same task elsewhere; general benchmarks only. GEO-Bench
`m-SA-crop-type` is South African crop type segmentation (Sentinel-2) and is the most
direct catalogued evidence for southern Africa crops; CropHarvest covers several
African countries (Kenya, Togo) and the "Africa crop mask" result in AlphaEarth is
sub-Saharan.
