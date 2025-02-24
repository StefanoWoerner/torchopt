# Copyright 2022-2023 MetaOPT Team. All Rights Reserved.
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
# ==============================================================================
# This file is modified from:
# https://github.com/deepmind/optax/blob/master/optax/_src/transform.py
# ==============================================================================
# Copyright 2019 DeepMind Technologies Limited. All Rights Reserved.
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
# ==============================================================================
"""Preset transformations for scaling updates by the root of the centered exponential moving average."""

# pylint: disable=invalid-name

from __future__ import annotations

from typing import NamedTuple

import torch

from torchopt import pytree
from torchopt.base import GradientTransformation
from torchopt.transform.utils import tree_map_flat, tree_map_flat_, update_moment
from torchopt.typing import OptState, Params, Updates


__all__ = ['scale_by_stddev']


class ScaleByRStdDevState(NamedTuple):
    """State for centered exponential moving average of squares of updates."""

    mu: Updates
    nu: Updates


def scale_by_stddev(
    alpha: float = 0.9,
    eps: float = 1e-8,
    initial_scale: float = 0.0,
) -> GradientTransformation:
    """Rescale updates by the root of the centered exponential moving average of squares.

    References:
        - Tieleman and Hinton, 2012: http://www.cs.toronto.edu/~hinton/coursera/lecture6/lec6.pdf

    Args:
        alpha (float, optional): Decay rate for the exponentially weighted average of squared grads.
            (default: :const:`0.9`)
        eps (float, optional): Term added to the denominator to improve numerical stability.
            (default: :const:`1e-8`)
        initial_scale (float, optional): Initial value for second moment. (default: :const:`0.0`)

    Returns:
        An (init_fn, update_fn) tuple.
    """
    return _scale_by_stddev(
        alpha=alpha,
        eps=eps,
        initial_scale=initial_scale,
        already_flattened=False,
    )


def _scale_by_stddev_flat(
    alpha: float = 0.9,
    eps: float = 1e-8,
    initial_scale: float = 0.0,
) -> GradientTransformation:
    return _scale_by_stddev(
        alpha=alpha,
        eps=eps,
        initial_scale=initial_scale,
        already_flattened=True,
    )


def _scale_by_stddev(
    alpha: float = 0.9,
    eps: float = 1e-8,
    initial_scale: float = 0.0,
    *,
    already_flattened: bool = False,
) -> GradientTransformation:
    # pylint: disable=unneeded-not
    if not alpha >= 0.0:  # pragma: no cover
        raise ValueError(f'Invalid alpha value: {alpha}')
    if not eps >= 0.0:  # pragma: no cover
        raise ValueError(f'Invalid epsilon value: {eps}')
    # pylint: enable=unneeded-not

    if already_flattened:
        tree_map = tree_map_flat
        tree_map_ = tree_map_flat_
    else:
        tree_map = pytree.tree_map  # type: ignore[assignment]
        tree_map_ = pytree.tree_map_  # type: ignore[assignment]

    def init_fn(params: Params) -> OptState:
        mu = tree_map(torch.zeros_like, params)  # first moment
        nu = tree_map(lambda n: torch.full_like(n, initial_scale), params)  # second moment
        return ScaleByRStdDevState(mu=mu, nu=nu)

    def update_fn(
        updates: Updates,
        state: OptState,
        *,
        params: Params | None = None,  # pylint: disable=unused-argument
        inplace: bool = True,
    ) -> tuple[Updates, OptState]:
        mu = update_moment.impl(  # type: ignore[attr-defined]
            updates,
            state.mu,
            alpha,
            order=1,
            inplace=inplace,
            already_flattened=already_flattened,
        )
        nu = update_moment.impl(  # type: ignore[attr-defined]
            updates,
            state.nu,
            alpha,
            order=2,
            inplace=inplace,
            already_flattened=already_flattened,
        )

        if inplace:

            def f(g: torch.Tensor, m: torch.Tensor, n: torch.Tensor) -> torch.Tensor:
                return g.div_(n.addcmul(m, m, value=-1.0).sqrt_().add(eps))

            updates = tree_map_(f, updates, mu, nu)

        else:

            def f(g: torch.Tensor, m: torch.Tensor, n: torch.Tensor) -> torch.Tensor:
                return g.div(n.addcmul(m, m, value=-1.0).sqrt_().add(eps))

            updates = tree_map(f, updates, mu, nu)

        return updates, ScaleByRStdDevState(mu=mu, nu=nu)

    return GradientTransformation(init_fn, update_fn)


scale_by_stddev.flat = _scale_by_stddev_flat  # type: ignore[attr-defined]
scale_by_stddev.impl = _scale_by_stddev  # type: ignore[attr-defined]
