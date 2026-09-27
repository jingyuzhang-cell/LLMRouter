"""Gaussian-process surrogate for Q(phi(G)) with epistemic uncertainty.

C and L are deterministic given (Y, X) profiles, so only Q needs a surrogate:
one GP over graph features. Small data (~tens of evaluations), Matern kernel.
"""
import numpy as np
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel


class QSurrogate:
    def fit(self, X, y):
        kernel = (ConstantKernel(0.2) * Matern(length_scale=np.ones(X.shape[1]), nu=1.5)
                  + WhiteKernel(0.02))
        self.model = GaussianProcessRegressor(kernel=kernel, normalize_y=True,
                                              n_restarts_optimizer=2, random_state=0)
        self.model.fit(X, y)

    def predict(self, X, return_std=True):
        return self.model.predict(X, return_std=return_std)
