# Data

Two CSV files are committed here. Nothing in the platform downloads data at run time: the training
job, the tests and the drift job all read these files.

| File | Rows | Size | SHA256 |
|---|---|---|---|
| `california_housing.csv` | 20640 | 1 329 396 bytes | `41f849ea4e9f9c46ce09cd7e4c900e3b06254f75567b12a81113273a4b528200` |
| `reference.csv` | 2500 | 161 091 bytes | `0aaf44f64845cd23186e9e2de7f2295f04e0057e543553255d84c96eb1a8e44c` |

The SHA256 of `california_housing.csv` is the dataset version. Every training run writes it to
MLflow as a run parameter and as the model version tag `dataset_sha256`. So it is always clear
which data a model was built from.

## Where the data comes from

The California Housing dataset, loaded once with
[`sklearn.datasets.fetch_california_housing`](https://scikit-learn.org/stable/modules/generated/sklearn.datasets.fetch_california_housing.html).
It was collected from the 1990 U.S. Census and published through StatLib. Each row is one census
block group, which is the smallest area the Census Bureau reports (600 to 3000 people).

Original source: Pace, R. Kelley and Ronald Barry, "Sparse Spatial Autoregressions", *Statistics
and Probability Letters*, 33 (1997), 291-297. The data comes from a U.S. Census product and is free
to redistribute. scikit-learn ships it as one of its public example datasets.

## Columns

The column order below is the order in both files.

| Column | Meaning | Unit |
|---|---|---|
| `MedInc` | median income in the block group | tens of thousands of dollars |
| `HouseAge` | median house age in the block group | years (capped at 52) |
| `AveRooms` | average number of rooms per household | rooms |
| `AveBedrms` | average number of bedrooms per household | rooms |
| `Population` | people living in the block group | people |
| `AveOccup` | average number of people per household | people |
| `Latitude` | centre of the block group | degrees north |
| `Longitude` | centre of the block group | degrees (negative = west) |
| `MedHouseVal` | median house value, the target | hundreds of thousands of dollars (capped at 5.00001) |

All nine columns are floating point numbers and there are no missing values.

### Rounding

The values are rounded when the file is written. `MedInc` (4 decimals), `HouseAge` and `Population`
(whole numbers), `Latitude` and `Longitude` (2 decimals) and `MedHouseVal` (5 decimals) lose nothing
at all. The source data has no more precision than that. Only `AveRooms`, `AveBedrms` and `AveOccup`
are cut, to 6 decimals. Without the rounding the file is 1.9 MB, which is close to the 2 MB limit of
the `check-added-large-files` pre-commit hook. With it the file is 1.3 MB. Six decimals on an
average room count has no effect on the model.

## reference.csv

The drift monitor compares live traffic against data the model has already seen. So `reference.csv`
holds 2500 rows **taken from the training split only**. The split is the same
`train_test_split(test_size=0.2, random_state=42, shuffle=True)` that
`services/training/training/preprocess.py` uses. This makes sure the rows are training rows and never
test rows. A test in the training service checks this
(`services/training/tests/test_data.py::test_reference_rows_come_from_the_train_split`).

The sample itself is drawn with `random_state=42` as well, so rebuilding the file gives exactly the
same rows.

## How to regenerate

Both scripts are standalone and run in a throw-away environment:

```bash
# from the root of the repository; needs network access
uv run --no-project --python 3.13 --with scikit-learn --with pandas \
    python final-project/scripts/fetch_dataset.py

# no network needed, reads california_housing.csv
uv run --no-project --python 3.13 --with scikit-learn --with pandas \
    python final-project/scripts/make_reference.py
```

`fetch_dataset.py` prints the row count, the size and the SHA256. If that hash changes, update the
table above. Every future model version will then carry the new `dataset_sha256`.
