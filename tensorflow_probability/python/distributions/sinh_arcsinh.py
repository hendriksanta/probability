# Copyright 2018 The TensorFlow Probability Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ============================================================================
"""SinhArcsinh transformation of a distribution."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow.compat.v2 as tf
from tensorflow_probability.python.bijectors import chain as chain_bijector
from tensorflow_probability.python.bijectors import identity as identity_bijector
from tensorflow_probability.python.bijectors import scale as scale_bijector
from tensorflow_probability.python.bijectors import shift as shift_bijector
from tensorflow_probability.python.bijectors import sinh_arcsinh as sinh_arcsinh_bijector
from tensorflow_probability.python.bijectors import softplus as softplus_bijector
from tensorflow_probability.python.distributions import normal
from tensorflow_probability.python.distributions import transformed_distribution
from tensorflow_probability.python.internal import distribution_util
from tensorflow_probability.python.internal import dtype_util
from tensorflow_probability.python.internal import parameter_properties
from tensorflow_probability.python.internal import tensor_util

__all__ = [
    'SinhArcsinh',
]


class SinhArcsinh(transformed_distribution.TransformedDistribution):
  """The SinhArcsinh transformation of a distribution on `(-inf, inf)`.

  This distribution models a random variable, making use of
  a `SinhArcsinh` transformation (which has adjustable tailweight and skew),
  a rescaling, and a shift.

  The `SinhArcsinh` transformation of the Normal is described in great depth in
  [Sinh-arcsinh distributions](https://www.jstor.org/stable/27798865).
  Here we use a slightly different parameterization, in terms of `tailweight`
  and `skewness`.  Additionally we allow for distributions other than Normal,
  and control over `scale` as well as a "shift" parameter `loc`.

  #### Mathematical Details

  Given random variable `Z`, we define the SinhArcsinh
  transformation of `Z`, `Y`, parameterized by
  `(loc, scale, skewness, tailweight)`, via the relation:

  ```
  Y := loc + scale * F(Z)
  F(Z) := Sinh( (Arcsinh(Z) + skewness) * tailweight ) * (2 / F_0(2))
  F_0(Z) := Sinh( Arcsinh(Z) * tailweight )
  ```

  This distribution is similar to the location-scale transformation
  `L(Z) := loc + scale * Z` in the following ways:

  * If `skewness = 0` and `tailweight = 1` (the defaults), `F(Z) = Z`, and then
    `Y = L(Z)` exactly.
  * `loc` is used in both to shift the result by a constant factor.
  * The multiplication of `scale` by `2 / F_0(2)` ensures that if `skewness = 0`
    `P[Y - loc <= 2 * scale] = P[L(Z) - loc <= 2 * scale]`.
    Thus it can be said that the weights in the tails of `Y` and `L(Z)` beyond
    `loc + 2 * scale` are the same.

  This distribution is different than `loc + scale * Z` due to the
  reshaping done by `F`:

  * Positive (negative) `skewness` leads to positive (negative) skew.
    * positive skew means, the mode of `F(Z)` is "tilted" to the right.
    * positive skew means positive values of `F(Z)` become more likely, and
      negative values become less likely.
  * Larger (smaller) `tailweight` leads to fatter (thinner) tails.
    * Fatter tails mean larger values of `|F(Z)|` become more likely.
    * `tailweight < 1` leads to a distribution that is "flat" around `Y = loc`,
      and a very steep drop-off in the tails.
    * `tailweight > 1` leads to a distribution more peaked at the mode with
      heavier tails.

  To see the argument about the tails, note that for `|Z| >> 1` and
  `|Z| >> (|skewness| * tailweight)**tailweight`, we have
  `Y approx 0.5 Z**tailweight e**(sign(Z) skewness * tailweight)`.

  To see the argument regarding multiplying `scale` by `2 / F_0(2)`,

  ```
  P[(Y - loc) / scale <= 2] = P[F(Z) * (2 / F_0(2)) <= 2]
                            = P[F(Z) <= F_0(2)]
                            = P[Z <= 2]  (if F = F_0).
  ```
  """

  def __init__(self,
               loc,
               scale,
               skewness=None,
               tailweight=None,
               distribution=None,
               validate_args=False,
               allow_nan_stats=True,
               name='SinhArcsinh'):
    """Construct SinhArcsinh distribution on `(-inf, inf)`.

    Arguments `(loc, scale, skewness, tailweight)` must have broadcastable shape
    (indexing batch dimensions).  They must all have the same `dtype`.

    Args:
      loc: Floating-point `Tensor`.
      scale:  `Tensor` of same `dtype` as `loc`.
      skewness:  Skewness parameter.  Default is `0.0` (no skew).
      tailweight:  Tailweight parameter. Default is `1.0` (unchanged tailweight)
      distribution: `tf.Distribution`-like instance. Distribution that is
        transformed to produce this distribution.
        Must have a batch shape to which the shapes of `loc`, `scale`,
        `skewness`, and `tailweight` all broadcast. Default is
        `tfd.Normal(batch_shape, 1.)`, where `batch_shape` is the broadcasted
        shape of the parameters. Typically
        `distribution.reparameterization_type = FULLY_REPARAMETERIZED` or it is
        a function of non-trainable parameters. WARNING: If you backprop through
        a `SinhArcsinh` sample and `distribution` is not
        `FULLY_REPARAMETERIZED` yet is a function of trainable variables, then
        the gradient will be incorrect!
      validate_args: Python `bool`, default `False`. When `True` distribution
        parameters are checked for validity despite possibly degrading runtime
        performance. When `False` invalid inputs may silently render incorrect
        outputs.
      allow_nan_stats: Python `bool`, default `True`. When `True`,
        statistics (e.g., mean, mode, variance) use the value "`NaN`" to
        indicate the result is undefined. When `False`, an exception is raised
        if one or more of the statistic's batch members are undefined.
      name: Python `str` name prefixed to Ops created by this class.
    """
    parameters = dict(locals())

    with tf.name_scope(name) as name:
      dtype = dtype_util.common_dtype([loc, scale, skewness, tailweight],
                                      tf.float32)
      self._loc = tensor_util.convert_nonref_to_tensor(
          loc, name='loc', dtype=dtype)
      self._scale = tensor_util.convert_nonref_to_tensor(
          scale, name='scale', dtype=dtype)
      tailweight = 1. if tailweight is None else tailweight
      has_default_skewness = skewness is None
      skewness = 0. if has_default_skewness else skewness
      self._tailweight = tensor_util.convert_nonref_to_tensor(
          tailweight, name='tailweight', dtype=dtype)
      self._skewness = tensor_util.convert_nonref_to_tensor(
          skewness, name='skewness', dtype=dtype)

      # Recall, with Z a random variable,
      #   Y := loc + scale * F(Z),
      #   F(Z) := Sinh( (Arcsinh(Z) + skewness) * tailweight ) * C
      #   C := 2 / F_0(2)
      #   F_0(Z) := Sinh( Arcsinh(Z) * tailweight )
      if distribution is None:
        batch_rank = tf.reduce_max([
            distribution_util.prefer_static_rank(x)
            for x in (self._skewness, self._tailweight, self._loc, self._scale)
        ])
        # TODO(b/160730249): Make `loc` a scalar `0.` and remove overridden
        # `batch_shape` and `batch_shape_tensor` when
        # TransformedDistribution's bijector can modify its `batch_shape`.
        distribution = normal.Normal(
            loc=tf.zeros(tf.ones(batch_rank, tf.int32), dtype=dtype),
            scale=tf.ones([], dtype=dtype),
            allow_nan_stats=allow_nan_stats,
            validate_args=validate_args)

      # Make the SAS bijector, 'F'.
      f = sinh_arcsinh_bijector.SinhArcsinh(
          skewness=self._skewness, tailweight=self._tailweight,
          validate_args=validate_args)

      # Make the AffineScalar bijector, Z --> loc + scale * Z (2 / F_0(2))
      affine = shift_bijector.Shift(shift=self._loc)(
          scale_bijector.Scale(scale=self._scale))
      bijector = chain_bijector.Chain([affine, f])

      super(SinhArcsinh, self).__init__(
          distribution=distribution,
          bijector=bijector,
          validate_args=validate_args,
          name=name)
      self._parameters = parameters

  @classmethod
  def _parameter_properties(cls, dtype, num_classes=None):
    return dict(
        loc=parameter_properties.ParameterProperties(),
        scale=parameter_properties.ParameterProperties(
            default_constraining_bijector_fn=(
                lambda: softplus_bijector.Softplus(low=dtype_util.eps(dtype)))),
        skewness=parameter_properties.ParameterProperties(),
        tailweight=parameter_properties.ParameterProperties(
            default_constraining_bijector_fn=(
                lambda: softplus_bijector.Softplus(low=dtype_util.eps(dtype)))))

  @property
  def loc(self):
    """The `loc` in `Y := loc + scale @ F(Z)`."""
    return self._loc

  @property
  def scale(self):
    """The `LinearOperator` `scale` in `Y := loc + scale @ F(Z)`."""
    return self._scale

  @property
  def tailweight(self):
    """Controls the tail decay.  `tailweight > 1` means faster than Normal."""
    return self._tailweight

  @property
  def skewness(self):
    """Controls the skewness.  `Skewness > 0` means right skew."""
    return self._skewness

  experimental_is_sharded = False

  def _batch_shape(self):
    params = [self.skewness, self.tailweight, self.loc, self.scale]
    s_shape = params[0].shape
    for t in params[1:]:
      s_shape = tf.broadcast_static_shape(s_shape, t.shape)
    return s_shape

  def _batch_shape_tensor(self):
    return distribution_util.get_broadcast_shape(
        self.skewness, self.tailweight, self.loc, self.scale)

  def _default_event_space_bijector(self):
    # TODO(b/145620027) Finalize choice of bijector.
    return identity_bijector.Identity(validate_args=self.validate_args)
