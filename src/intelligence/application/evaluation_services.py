from typing import List, Optional
from src.intelligence.domain.models import DatasetRecord, ConfusionMatrix, BaselineEvaluationReport


def _calculate_confusion_matrix(tp: int, fp: int, tn: int, fn: int) -> ConfusionMatrix:
    precision = float(tp) / (tp + fp) if (tp + fp) > 0 else None
    recall = float(tp) / (tp + fn) if (tp + fn) > 0 else None
    specificity = float(tn) / (tn + fp) if (tn + fp) > 0 else None
    return ConfusionMatrix(
        tp=tp,
        fp=fp,
        tn=tn,
        fn=fn,
        precision=precision,
        recall=recall,
        specificity=specificity
    )


class EvaluateRuleBasedBaselineService:
    """Usecase to evaluate the rule-based baseline model accuracy against outcomes in pure Python.

    Constructs confusion matrices, precision, recall, and specificity for SLA and Thermal predictions.
    """

    def evaluate(self, records: List[DatasetRecord]) -> BaselineEvaluationReport:
        sla_tp = sla_fp = sla_tn = sla_fn = 0
        thermal_tp = thermal_fp = thermal_tn = thermal_fn = 0
        total_records = len(records)

        for rec in records:
            if rec.eligibility != "COMPLETE":
                continue

            # 1. Evaluate SLA rules
            # We check if features snapshot predicted SLA overdue or margin low/critical
            features = rec.features or {}
            labels = rec.labels or {}

            # Predictor: risk indicators for SLA
            predicted_sla_risk = (
                features.get("sla_overdue", False) or
                (features.get("has_sla", False) and features.get("sla_margin_min") is not None and features.get("sla_margin_min", 999) < 120)
            )
            actual_sla_breach = labels.get("sla_breached")

            if actual_sla_breach is not None:
                if predicted_sla_risk and actual_sla_breach:
                    sla_tp += 1
                elif predicted_sla_risk and not actual_sla_breach:
                    sla_fp += 1
                elif not predicted_sla_risk and not actual_sla_breach:
                    sla_tn += 1
                elif not predicted_sla_risk and actual_sla_breach:
                    sla_fn += 1

            # 2. Evaluate Thermal rules
            predicted_thermal_risk = (
                features.get("has_thermal_requirement", False) and (
                    features.get("thermal_excursion_count", 0) > 0 or
                    features.get("temperature_below_min", False) or
                    features.get("temperature_above_max", False)
                )
            )
            actual_thermal_excursion = labels.get("thermal_excursion_occurred")

            if actual_thermal_excursion is not None:
                if predicted_thermal_risk and actual_thermal_excursion:
                    thermal_tp += 1
                elif predicted_thermal_risk and not actual_thermal_excursion:
                    thermal_fp += 1
                elif not predicted_thermal_risk and not actual_thermal_excursion:
                    thermal_tn += 1
                elif not predicted_thermal_risk and actual_thermal_excursion:
                    thermal_fn += 1

        sla_cm = _calculate_confusion_matrix(sla_tp, sla_fp, sla_tn, sla_fn)
        thermal_cm = _calculate_confusion_matrix(thermal_tp, thermal_fp, thermal_tn, thermal_fn)

        # False positive / negative rates
        total_fps = sla_fp + thermal_fp
        total_fns = sla_fn + thermal_fn
        total_preds = (sla_tp + sla_fp + sla_tn + sla_fn) + (thermal_tp + thermal_fp + thermal_tn + thermal_fn)

        false_positive_rate = float(total_fps) / total_preds if total_preds > 0 else 0.0
        false_negative_rate = float(total_fns) / total_preds if total_preds > 0 else 0.0

        return BaselineEvaluationReport(
            sla_evaluation=sla_cm,
            thermal_evaluation=thermal_cm,
            total_evaluated_records=total_records,
            false_positive_rate=round(false_positive_rate, 4),
            false_negative_rate=round(false_negative_rate, 4),
        )
