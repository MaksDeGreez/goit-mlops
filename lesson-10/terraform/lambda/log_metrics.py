"""Second step of the training pipeline: log the metrics of the run.

In a real pipeline the metrics would come from the training step and would be
sent to a tracking server such as MLflow. Here they are calculated from the
input so that the output of the workflow is predictable.
"""

import json


def lambda_handler(event, context):
    print("Logging metrics...")

    validation = event.get("validation", {})
    rows = validation.get("rows", 0)

    # Simple numbers instead of a real training result.
    metrics = {
        "rows_used": rows,
        "accuracy": 0.93,
        "loss": 0.21,
    }

    print(json.dumps({"commit": event.get("commit"), "metrics": metrics}))
    print("Metrics logged")

    return {
        **event,
        "metrics": metrics,
        "status": "completed",
    }
