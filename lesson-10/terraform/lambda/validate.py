"""First step of the training pipeline: check the input data.

In a real pipeline this step would read the dataset and check its schema,
its size and the share of missing values. Here the check is simplified:
the function verifies that the workflow received the fields it needs.
"""

import json


REQUIRED_FIELDS = ("source", "commit")
MIN_ROWS = 1


def lambda_handler(event, context):
    print("Validating data...")
    print(f"Received input: {json.dumps(event)}")

    missing = [field for field in REQUIRED_FIELDS if not event.get(field)]
    if missing:
        # Raising an exception fails the Step Functions state, so a bad input
        # stops the pipeline instead of training on it.
        raise ValueError(f"Missing required fields: {', '.join(missing)}")

    rows = int(event.get("rows", 150))
    if rows < MIN_ROWS:
        raise ValueError(f"Dataset is too small: {rows} rows")

    print(f"Validation passed: {rows} rows, source={event['source']}, commit={event['commit']}")

    # Everything returned here becomes the input of the next step.
    return {
        **event,
        "validation": {
            "status": "passed",
            "rows": rows,
            "checked_fields": list(REQUIRED_FIELDS),
        },
    }
