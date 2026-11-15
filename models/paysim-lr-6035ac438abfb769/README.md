# Trained PaySim scorer

These are the exact locally trained model and calibrator used in the frozen experiment. No retraining is needed to run the demo.

- `model.joblib`: scikit-learn Logistic Regression preprocessing/model pipeline.
- `calibrator.joblib`: logistic calibration fitted only on steps401–470.
- `metadata.json`: feature names, model version and full source/model/calibrator SHA256s.

Model version: `paysim-lr-6035ac438abfb769`. Training steps1–400, calibration401–470. Locked package versions are in `../requirements.lock.txt`. The service loads trusted bundled bytes only after their hashes match metadata. Metadata and artifact bytes were not changed to package the demo.

Dataset attribution: Edgar Alonso Lopez-Rojas, PaySim, https://www.kaggle.com/datasets/ealaxi/paysim1 . The source dataset is CC BY-SA4.0. These dataset-derived trained artifacts are distributed under CC BY-SA4.0 as well; see https://creativecommons.org/licenses/by-sa/4.0/ . Source and numerical parameters of the original PaySim dataset were not changed; these artifacts are the fitted ML transformation. No endorsement by the source author is implied. Application source code remains under the repository MIT licence.
