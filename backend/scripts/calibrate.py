"""Calibration harness for the synthetic generator.

Reports the Day-5 verification statistics of the demonstration dataset so that
`SIGMA_SCALE` in `app/core/synthetic.py` can be tuned to physically plausible
medium-range error magnitudes. Run:  python -m scripts.calibrate
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from app.config import settings
from app.core.domain import ALL_SITES, VARIABLES
from app.core.verification import error_record, model_performance, verification_valid_days

TARGET_RMSE = {"rainfall": 18.0, "temperature": 2.0, "wind": 1.7, "pressure": 2.2}


def main() -> None:
    base = date.fromisoformat(settings.demo_reference_date)
    print(f"{'variable':<12}{'RMSE':>9}{'target':>9}{'factor':>9}{'MAE':>9}{'bust rate':>11}")
    for var in VARIABLES:
        errs, busts = [], []
        for valid in verification_valid_days(base, 60):
            init = valid - timedelta(days=5)
            for loc in ALL_SITES:
                rec = error_record(loc.id, var.id, init, 5)
                errs.append(rec.error)
                busts.append(rec.bust)
        e = np.array(errs)
        rmse = float(np.sqrt(np.mean(e**2)))
        target = TARGET_RMSE[var.id]
        print(
            f"{var.id:<12}{rmse:>9.2f}{target:>9.2f}{target / rmse:>9.3f}"
            f"{float(np.mean(np.abs(e))):>9.2f}{float(np.mean(busts)):>11.3f}"
        )

    perf = model_performance(base)
    print(
        f"\nrisk model: ROC-AUC={perf['roc_auc']}  Brier={perf['brier_score']}  "
        f"P={perf['precision']}  R={perf['recall']}  F1={perf['f1']}  "
        f"base rate={perf['base_rate']}  n={perf['sample_size']}"
    )


if __name__ == "__main__":
    main()
