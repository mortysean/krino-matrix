"""The KRINO Matrix model: one shared encoder reads a whole decision case, three heads answer its tasks.

  network.py     MatrixModel, the network both frameworks share
  training/      training, calibration and benchmarking (trainer.py, and the train.py / benchmark.py commands)
  inference/     MatrixEvaluator: one forward pass, hard-constraint filter, then selection
  checkpoints/   trained weights, kept locally (mmbert-uncertainty is the one the web app runs)
"""
