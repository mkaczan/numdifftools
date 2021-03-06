"""numerical differentiation function, gradient, Jacobian, and Hessian

Author : pbrod, josef-pkt
License : BSD
Notes
-----
These are simple forward differentiation, so that we have them available
without dependencies.
* Jacobian should be faster than numdifftools.core because it doesn't use loop
  over observations.
* numerical precision will vary and depend on the choice of stepsizes
"""

# TODO:
# * some cleanup
# * check numerical accuracy (and bugs) with numdifftools and analytical
#   derivatives
#   - linear least squares case: (hess - 2*X'X) is 1e-8 or so
#   - gradient and Hessian agree with numdifftools when evaluated away from
#     minimum
#   - forward gradient, Jacobian evaluated at minimum is inaccurate, centered
#     (+/- base_step) is ok
# * dot product of Jacobian is different from Hessian, either wrong example or
#   a bug (unlikely), or a real difference
#
#
# What are the conditions that Jacobian dotproduct and Hessian are the same?
#
# See also:
#
# BHHH: Greene p481 17.4.6,  MLE Jacobian = d loglike / d beta , where loglike
# is vector for each observation
#    see also example 17.4 when J'J is very different from Hessian
#    also does it hold only at the minimum, what's relationship to covariance
#    of Jacobian matrix
# http://projects.scipy.org/scipy/ticket/1157
# http://en.wikipedia.org/wiki/Levenberg%E2%80%93Marquardt_algorithm
#    objective: sum((y-f(beta,x)**2),   Jacobian = d f/d beta
#    and not d objective/d beta as in MLE Greene similar:
# http://crsouza.blogspot.com/2009/11/neural-network-learning-by-levenberg_18.html#hessian
#
# in example: if J = d x*beta / d beta then J'J == X'X
#    similar to
#    http://en.wikipedia.org/wiki/Levenberg%E2%80%93Marquardt_algorithm
from __future__ import print_function
import numpy as np
from numdifftools import dea3
from collections import namedtuple
from matplotlib import pyplot as plt
# NOTE: we only do double precision internally so far
EPS = np.MachAr().eps


def _make_exact(h):
    '''Make sure h is an exact representable number
    This is important when calculating numerical derivatives and is
    accomplished by adding 1 and then subtracting 1..
    '''
    return (h + 1.0) - 1.0


def _default_base_step(x, scale, epsilon=None):
    if epsilon is None:
        h = (10 * EPS) ** (1. / scale) * np.maximum(np.log1p(np.abs(x)), 0.1)
    else:
        if np.isscalar(epsilon):
            h = np.ones(x.shape) * epsilon
        else:
            h = np.asarray(epsilon)
            if h.shape != x.shape:
                raise ValueError("If h is not a scalar it must have the same"
                                 " shape as x.")
    return h


_cmn_doc = """
    Calculate %(derivative)s with finite difference approximation

    Parameters
    ----------
    f : function
       function of one array f(x, `*args`, `**kwargs`)
    steps : float, array-like or StepsGenerator object, optional
       Spacing used, if None, then the spacing is automatically chosen
       according to (10*EPS)**(1/scale)*max(log(1+|x|), 0.1) where scale is
       depending on method.
       A StepsGenerator can be used to extrapolate the results. However,
       the generator must generate minimum 3 steps in order to extrapolate
       the values.
    method : string, optional
        defines method used in the approximation
        'complex': complex-step derivative (scale=%(scale_complex)s)
        'central': central difference derivative (scale=%(scale_central)s)
        'backward': forward difference derivative (scale=%(scale_backward)s)
        'forward': forward difference derivative (scale=%(scale_forward)s)
        %(extra_method)s
    full_output : bool, optional
        If `full_output` is False, only the derivative is returned.
        If `full_output` is True, then (der, r) is returned `der` is the
        derivative, and `r` is a Results object.

    Call Parameters
    ---------------
    x : array_like
       value at which function derivative is evaluated
    args : tuple
        Arguments for function `f`.
    kwds : dict
        Keyword arguments for function `f`.
    %(returns)s
    Notes
    -----
    The complex-step derivative has truncation error O(steps**2), so
    truncation error can be eliminated by choosing steps to be very small.
    The complex-step derivative avoids the problem of round-off error with
    small steps because there is no subtraction. However, the function
    needs to be analytic. This method does not work if f(x) involves non-
    analytic functions such as e.g.: abs, max, min
    %(extra_note)s
    References
    ----------
    Ridout, M.S. (2009) Statistical applications of the complex-step method
        of numerical differentiation. The American Statistician, 63, 66-74
    %(example)s
    %(see_also)s
    """


class StepsGenerator(object):
    '''
    Generates a sequence of steps

    where
        steps = base_step * step_ratio ** (np.arange(num_steps) + offset)

    Parameters
    ----------
    base_step : float, array-like, optional
       Defines the base step, if None, then base_step is set to
           (10*EPS)**(1/scale)*max(log(1+|x|), 0.1)
       where x and scale are supplied at runtime through the __call__ method.
    num_steps : scalar integer, optional
        defines number of steps generated.
    step_ratio : real scalar, optional
        Ratio between sequential steps generated.
        Note: Ratio > 1
    offset : real scalar, optional
        offset
    '''

    def __init__(self, base_step=None, num_steps=10, step_ratio=4, offset=-1,
                 use_exact_steps=True):
        self.base_step = base_step
        self.num_steps = num_steps
        self.step_ratio = step_ratio
        self.offset = offset
        self.use_exact_steps = use_exact_steps

    def _default_base_step(self, xi, scale):
        delta = _default_base_step(xi, scale, self.base_step)
        if self.use_exact_steps:
            return _make_exact(delta)
        return delta

    def __call__(self, x, scale=1.5):
        xi = np.asarray(x)
        delta = self._default_base_step(xi, scale)

        step_ratio, offset = float(self.step_ratio), self.offset
        for i in range(int(self.num_steps), -1, -1):
            h = (delta * step_ratio**(i + offset))
            if (np.abs(h) > 0).all():
                yield h


class StepsGenerator2(object):
    '''
    Generates a sequence of steps

    where
        steps = logspace(np.log10(step_min),np.log10(step_max), num_steps)

    Parameters
    ----------
    step_min : float, array-like, optional
       Defines the minimim step if None, then base_step is set to
           (10*EPS)**(1/scale)*max(log(1+|x|), 0.1)
       where x and scale are supplied at runtime through the __call__ method.
    num_steps : scalar integer, optional
        defines number of steps generated.
    step_max : real scalar, optional
        maximum step generated.

    '''

    def __init__(self, step_min=None, num_steps=10, step_max=None):
        self.step_min = step_min
        self.num_steps = num_steps
        self.step_max = step_max

    def __call__(self, x, scale=1.5):
        xi = np.asarray(x)
        step_min, step_max = self.step_min, self.step_max
        delta = _default_base_step(xi, scale, step_min)
        if step_min is None:
            step_min = (10 * EPS)**(1. / scale)
        if step_max is None:
            step_max = (10 * EPS)**(1. / (scale + 1.5))
        steps = np.logspace(0, -np.log10(step_min) + np.log10(step_max),
                            self.num_steps)[::-1]

        for step in steps:
            h = _make_exact(delta * step)
            if (np.abs(h) > 0).all():
                yield h


class _Derivative(object):

    @staticmethod
    def default_scale(method, n=1):
        return dict(complex=1, central=3).get(method, 2) + (n-1)

    info = namedtuple('info', ['error_estimate', 'index'])

    @property
    def scale(self):
        if self._scale is None:
            return self.default_scale(self.method, self.n)
        return self._scale

    @scale.setter
    def scale(self, scale):
        self._scale = scale

    def __init__(self, f, steps=None, method='complex', full_output=False,
                 scale=None):
        self.n = 1
        self.f = f
        self._scale = scale
        self.steps = self._make_callable(steps)
        self.method = method
        self.full_output = full_output

    def _make_callable(self, steps):
        if hasattr(steps, '__call__'):
            return steps

        def _step_generator(xi, scale):
            yield _default_base_step(xi, scale, steps)
        return _step_generator

    def _get_functions(self, method):
        return getattr(self, '_' + self.method), self.f, self.steps

    def __call__(self, x, *args, **kwds):
        xi = np.asarray(x)
        derivative, f, steps = self._get_functions(self.method)
        results = [derivative(f, xi, h, *args, **kwds)
                   for h in steps(xi, self.scale)]
        derivative, info = self._extrapolate(results)
        if self.full_output:
            return derivative, info
        return derivative

    def _get_arg_min(self, errors):
        shape = errors.shape
        arg_mins = np.nanargmin(errors, axis=0)
        min_errors = np.nanmin(errors, axis=0)
        for i, min_error in enumerate(min_errors):
            idx = np.flatnonzero(errors[:, i] == min_error)
            arg_mins[i] = idx[idx.size // 2]
        ix = np.ravel_multi_index((arg_mins, np.arange(shape[1])), shape)
        return ix

    def _extrapolate(self, sequence):

        dont_extrapolate = len(sequence) < 3
        if dont_extrapolate:
            err = np.empty_like(sequence[0])
            err.fill(np.NaN)
            return 0.5 * (sequence[0] + sequence[-1]), self.info(err, 0)

        original_shape = sequence[0].shape
        res = np.vstack(r.ravel() for r in sequence)
        der, errors = dea3(res[0:-2], res[1:-1], res[2:], symmetric=True)
        if len(der) > 2:
            der, errors = dea3(der[0:-2], der[1:-1], der[2:])
        ix = self._get_arg_min(errors)

        err = errors.flat[ix].reshape(original_shape)
        return der.flat[ix].reshape(original_shape), self.info(err, ix)


class NDerivative(_Derivative):
    """
    Find the n-th derivative of a function at a point.

    Given a function, use a central difference formula with spacing `dx` to
    compute the `n`-th derivative at `x0`.

    Parameters
    ----------
    f : function
        Input function.
    x0 : float
        The point at which `n`-th derivative is found.
    dx : float, optional
        Spacing.
    n : int, optional
        Order of the derivative. Default is 1.
    order : int, optional
        Number of points to use, must be odd.

    Notes
    -----
    Decreasing the step size too small can result in round-off error.

    Examples
    --------
    >>> def f(x):
    ...     return x**3 + x**2

    >>> df = NDerivative(f)
    >>> np.allclose(df(1), 5)
    True
    >>> ddf = NDerivative(f, n=2)
    >>> np.allclose(ddf(1), 8)
    True
    """

    def __init__(self, f, steps=None, method='central', full_output=False,
                 scale=None, n=1, order=3):
        super(NDerivative, self).__init__(f, steps, method, full_output, scale)
        self.order = order
        self.n = n
        self.weights = self._weights(n, order)

    @staticmethod
    def central_diff_weights(Np, ndiv=1):
        """
        Return weights for an Np-point central derivative.

        Assumes equally-spaced function points.

        If weights are in the vector w, then
        derivative is w[0] * f(x-ho*dx) + ... + w[-1] * f(x+h0*dx)

        Parameters
        ----------
        Np : int
            Number of points for the central derivative.
        ndiv : int, optional
            Number of divisions.  Default is 1.

        Notes
        -----
        Can be inaccurate for large number of points.

        """
        if Np < ndiv + 1:
            raise ValueError(
                "Number of points must be at least the derivative order + 1.")
        if Np % 2 == 0:
            raise ValueError("The number of points must be odd.")
        from scipy import linalg
        ho = Np >> 1
        x = np.arange(-ho, ho + 1.0)
        x = x[:, np.newaxis]
        X = x**0.0
        for k in range(1, Np):
            X = np.hstack([X, x**k])
        w = np.product(np.arange(1, ndiv + 1), axis=0) * linalg.inv(X)[ndiv]
        return w

    def _weights(self, n, order):
        array = np.array
        if order < n + 1:
            raise ValueError("'order' (the number of points used to compute "
                             "the derivative), must be at least the "
                             "derivative order 'n' + 1.")
        if order % 2 == 0:
            raise ValueError("'order' (the number of points used to compute "
                             "the derivative)  must be odd.")
            # pre-computed for n=1 and 2 and low-order for speed.
        if n == 1:
            if order == 3:
                weights = array([-1, 0, 1]) / 2.0
            elif order == 5:
                weights = array([1, -8, 0, 8, -1]) / 12.0
            elif order == 7:
                weights = array([-1, 9, -45, 0, 45, -9, 1]) / 60.0
            elif order == 9:
                weights = array(
                    [3, -32, 168, -672, 0, 672, -168, 32, -3]) / 840.0
            else:
                weights = self.central_diff_weights(order, 1)
        elif n == 2:
            if order == 3:
                weights = array([1, -2.0, 1])
            elif order == 5:
                weights = array([-1, 16, -30, 16, -1]) / 12.0
            elif order == 7:
                weights = array([2, -27, 270, -490, 270, -27, 2]) / 180.0
            elif order == 9:
                weights = array([-9, 128, -1008, 8064, -14350,
                                 8064, -1008, 128, -9]) / 5040.0
            else:
                weights = self.central_diff_weights(order, 2)
        else:
            weights = self.central_diff_weights(order, n)
        return weights

    def _central(self, f, x0, dx, *args, **kwds):
        val = 0.0
        ho = self.order >> 1
        for k, w in enumerate(self.weights):
            val += w * f(x0 + (k - ho) * dx, *args, **kwds)
        return val / np.product((dx,) * self.n, axis=0)


class Derivative(_Derivative):
    __doc__ = _cmn_doc % dict(
        derivative='first order derivative',
        scale_backward=str(_Derivative.default_scale('backward')),
        scale_central=str(_Derivative.default_scale('central')),
        scale_complex=str(_Derivative.default_scale('complex')),
        scale_forward=str(_Derivative.default_scale('forward')),
        extra_method="",
        extra_note='', returns="""
    Returns
    -------
    der : ndarray
       array of derivatives
    """, example="""
    Examples
    --------
    >>> import numpy as np
    >>> import numdifftools.nd_cstep as ndc

    # 1'st derivative of exp(x), at x == 1

    >>> fd = ndc.Derivative(np.exp)       # 1'st derivative
    >>> np.allclose(fd(1), 2.71828183)
    True

    >>> d2 = fd([1, 2])
    >>> d2
    array([ 2.71828183,  7.3890561 ])""", see_also="""
    See also
    --------
    Gradient,
    Hessian
    """)

    def _central(self, f, x, h, *args, **kwds):
        h2 = h * 2
        return (f(x + h, *args, **kwds) - f(x - h, *args, **kwds)) / h2

    def _forward(self, f, x, h, *args, **kwds):
        return (f(x + h, *args, **kwds) - f(x, *args, **kwds)) / h

    def _backward(self, f, x, h, *args, **kwds):
        return (f(x, *args, **kwds) - f(x - h, *args, **kwds)) / h

    def _complex(self, f, x, h, *args, **kwds):
        return f(x + 1j * h, *args, **kwds).imag / h


class Gradient(_Derivative):
    __doc__ = _cmn_doc % dict(
        derivative='Gradient',
        scale_backward=str(_Derivative.default_scale('backward')),
        scale_central=str(_Derivative.default_scale('central')),
        scale_complex=str(_Derivative.default_scale('complex')),
        scale_forward=str(_Derivative.default_scale('forward')),
        extra_method="",
        returns="""
    Returns
    -------
    grad : array
        gradient
    """, extra_note="""
    If f returns a 1d array, it returns a Jacobian. If a 2d array is returned
    by f (e.g., with a value for each observation), it returns a 3d array
    with the Jacobian of each observation with shape xk x nobs x xk. I.e.,
    the Jacobian of the first observation would be [:, 0, :]
    """, example="""
    Examples
    --------
    >>> import numpy as np
    >>> import numdifftools.nd_cstep as ndc
    >>> fun = lambda x: np.sum(x**2)
    >>> dfun = ndc.Gradient(fun)
    >>> dfun([1,2,3])
    array([ 2.,  4.,  6.])

    # At [x,y] = [1,1], compute the numerical gradient
    # of the function sin(x-y) + y*exp(x)

    >>> sin = np.sin; exp = np.exp
    >>> z = lambda xy: sin(xy[0]-xy[1]) + xy[1]*exp(xy[0])
    >>> dz = ndc.Gradient(z)
    >>> grad2 = dz([1, 1])
    >>> grad2
    array([ 3.71828183,  1.71828183])

    # At the global minimizer (1,1) of the Rosenbrock function,
    # compute the gradient. It should be essentially zero.

    >>> rosen = lambda x : (1-x[0])**2 + 105.*(x[1]-x[0]**2)**2
    >>> rd = ndc.Gradient(rosen)
    >>> grad3 = rd([1,1])
    >>> np.allclose(grad3,[0, 0])
    True""", see_also="""
    See also
    --------
    Derivative, Hessian, Jacobian
    """)

    def _central(self, f, x, h, *args, **kwds):
        n = len(x)
        increments = np.identity(n) * h
        h2 = h * 2.0
        partials = [(f(x + hi, *args, **kwds) -
                     f(x - hi, *args, **kwds)) / (h2[i])
                    for i, hi in enumerate(increments)]
        return np.array(partials).T

    def _backward(self, f, x, epsilon, *args, **kwds):
        n = len(x)
        increments = np.identity(n) * epsilon
        f0 = f(x, *args, **kwds)
        partials = [(f0 - f(x - h, *args, **kwds)) / epsilon[i]
                    for i, h in enumerate(increments)]
        return np.array(partials).T

    def _forward(self, f, x, epsilon, *args, **kwds):
        n = len(x)
        increments = np.identity(n) * epsilon
        f0 = f(x, *args, **kwds)
        partials = [(f(x + h, *args, **kwds) - f0) / epsilon[i]
                    for i, h in enumerate(increments)]
        return np.array(partials).T

    def _complex(self, f, x, epsilon, *args, **kwds):
        # From Guilherme P. de Freitas, numpy mailing list
        # http://mail.scipy.org/pipermail/numpy-discussion/2010-May/050250.html
        n = len(x)
        increments = np.identity(n) * 1j * epsilon
        partials = [f(x + ih, *args, **kwds).imag / epsilon[i]
                    for i, ih in enumerate(increments)]
        return np.array(partials).T


class Jacobian(Gradient):
    __doc__ = _cmn_doc % dict(
        derivative='Jacobian',
        scale_backward=str(_Derivative.default_scale('backward')),
        scale_central=str(_Derivative.default_scale('central')),
        scale_complex=str(_Derivative.default_scale('complex')),
        scale_forward=str(_Derivative.default_scale('forward')),
        extra_method="",
        returns="""
    Returns
    -------
    jacob : array
        Jacobian
    """, extra_note="""
    If f returns a 1d array, it returns a Jacobian. If a 2d array is returned
    by f (e.g., with a value for each observation), it returns a 3d array
    with the Jacobian of each observation with shape xk x nobs x xk. I.e.,
    the Jacobian of the first observation would be [:, 0, :]
    """, example='''
     Examples
    --------
    >>> import numdifftools.nd_cstep as ndc

    #(nonlinear least squares)

    >>> xdata = np.reshape(np.arange(0,1,0.1),(-1,1))
    >>> ydata = 1+2*np.exp(0.75*xdata)
    >>> fun = lambda c: (c[0]+c[1]*np.exp(c[2]*xdata) - ydata)**2

    >>> Jfun = ndc.Jacobian(fun)
    >>> Jfun([1,2,0.75]).reshape((3,-1)) # should be numerically zero
    array([[ 0.,  0.,  0.,  0.,  0.,  0.,  0.,  0.,  0.,  0.],
           [ 0.,  0.,  0.,  0.,  0.,  0.,  0.,  0.,  0.,  0.],
           [ 0.,  0.,  0.,  0.,  0.,  0.,  0.,  0.,  0.,  0.]])

    >>> fun2 = lambda x : x[0]*x[1]*x[2] + np.exp(x[0])*x[1]
    >>> Jfun3 = ndc.Jacobian(fun2)
    >>> Jfun3([3.,5.,7.])
    array([ 135.42768462,   41.08553692,   15.        ])
    ''', see_also="""
    See also
    --------
    Derivative, Hessian, Gradient
    """)


class _Hessian(_Derivative):

    @staticmethod
    def default_scale(method, n=2):
        return dict(central=8, central2=8, complex=6).get(method, 4)


class Hessian(_Hessian):
    __doc__ = _cmn_doc % dict(
        derivative='Hessian',
        scale_backward=str(_Hessian.default_scale('backward')),
        scale_central=str(_Hessian.default_scale('central')),
        scale_complex=str(_Hessian.default_scale('complex')),
        scale_forward=str(_Hessian.default_scale('forward')),
        extra_method="'central2' : central difference derivative "
        "(scale=%s)" % _Hessian.default_scale('central2'),
        returns="""
    Returns
    -------
    hess : ndarray
       array of partial second derivatives, Hessian
    """, extra_note="""Computes the Hessian according to method as:
    'forward', Eq. (7):
        1/(d_j*d_k) * ((f(x + d[j]*e[j] + d[k]*e[k]) - f(x + d[j]*e[j])))
    'central2', Eq. (8):
        1/(2*d_j*d_k) * ((f(x + d[j]*e[j] + d[k]*e[k]) - f(x + d[j]*e[j])) -
                         (f(x + d[k]*e[k]) - f(x)) +
                         (f(x - d[j]*e[j] - d[k]*e[k]) - f(x + d[j]*e[j])) -
                         (f(x - d[k]*e[k]) - f(x)))
    'central', Eq. (9):
        1/(4*d_j*d_k) * ((f(x + d[j]*e[j] + d[k]*e[k]) -
                          f(x + d[j]*e[j] - d[k]*e[k])) -
                         (f(x - d[j]*e[j] + d[k]*e[k]) -
                          f(x - d[j]*e[j] - d[k]*e[k]))
    'complex', Eq. (10):
        1/(2*d_j*d_k) * imag(f(x + i*d[j]*e[j] + d[k]*e[k]) -
                            f(x + i*d[j]*e[j] - d[k]*e[k]))
    where e[j] is a vector with element j == 1 and the rest are zero and
    d[i] is steps[i].
    """, example="""
    Examples
    --------
    >>> import numpy as np
    >>> import numdifftools.nd_cstep as ndc

    # Rosenbrock function, minimized at [1,1]

    >>> rosen = lambda x : (1.-x[0])**2 + 105*(x[1]-x[0]**2)**2
    >>> Hfun = ndc.Hessian(rosen)
    >>> h = Hfun([1, 1])
    >>> h
    array([[ 842., -420.],
           [-420.,  210.]])

    # cos(x-y), at (0,0)

    >>> cos = np.cos
    >>> fun = lambda xy : cos(xy[0]-xy[1])
    >>> Hfun2 = ndc.Hessian(fun)
    >>> h2 = Hfun2([0, 0])
    >>> h2
    array([[-1.,  1.],
           [ 1., -1.]])""", see_also="""
    See also
    --------
    Derivative, Hessian
    """)

    def _complex(self, f, x, h, *args, **kwargs):
        '''Calculate Hessian with complex-step derivative approximation
        The stepsize is the same for the complex and the finite difference part
        '''
        # TODO: might want to consider lowering the step for pure derivatives
        n = len(x)
        # h = _default_base_step(x, 3, base_step, n)
        ee = np.diag(h)
        hess = 2. * np.outer(h, h)

        for i in range(n):
            for j in range(i, n):
                hess[i, j] = (f(x + 1j * ee[i, :] + ee[j, :], *args,
                                **kwargs) -
                              f(*((x + 1j * ee[i, :] - ee[j, :],) + args),
                                  **kwargs)).imag / hess[j, i]
                hess[j, i] = hess[i, j]
        return hess

    def _central(self, f, x, h, *args, **kwargs):
        '''Eq 9.'''
        n = len(x)
        # h = _default_base_step(x, 4, base_step, n)
        ee = np.diag(h)
        hess = np.outer(h, h)

        for i in range(n):
            for j in range(i, n):
                hess[i, j] = (f(x + ee[i, :] + ee[j, :], *args, **kwargs) -
                              f(x + ee[i, :] - ee[j, :], *args, **kwargs) -
                              f(x - ee[i, :] + ee[j, :], *args, **kwargs) +
                              f(x - ee[i, :] - ee[j, :], *args, **kwargs)
                              ) / (4. * hess[j, i])
                hess[j, i] = hess[i, j]
        return hess

    def _central2(self, f, x, h, *args, **kwargs):
        '''Eq. 8'''
        n = len(x)
        # NOTE: ridout suggesting using eps**(1/4)*theta
        # h = _default_base_step(x, 3, base_step, n)
        ee = np.diag(h)
        f0 = f(x, *args, **kwargs)
        dtype = np.result_type(f0)
        g = np.empty(n, dtype=dtype)
        gg = np.empty(n, dtype=dtype)
        for i in range(n):
            g[i] = f(x + ee[i, :], *args, **kwargs)
            gg[i] = f(x - ee[i, :], *args, **kwargs)

        hess = np.empty((n, n), dtype=dtype)
        np.outer(h, h, out=hess)
        for i in range(n):
            for j in range(i, n):
                hess[i, j] = (f(x + ee[i, :] + ee[j, :], *args, **kwargs) -
                              g[i] - g[j] + f0 +
                              f(x - ee[i, :] - ee[j, :], *args, **kwargs) -
                              gg[i] - gg[j] + f0) / (2 * hess[j, i])
                hess[j, i] = hess[i, j]

        return hess

    def _forward(self, f, x, h, *args, **kwargs):
        '''Eq. 7'''
        n = len(x)
        ee = np.diag(h)

        f0 = f(x, *args, **kwargs)
        dtype = np.result_type(f0)
        g = np.empty(n, dtype=dtype)
        for i in range(n):
            g[i] = f(x + ee[i, :], *args, **kwargs)

        hess = np.empty((n, n), dtype=dtype)
        np.outer(h, h, out=hess)
        for i in range(n):
            for j in range(i, n):
                hess[i, j] = (f(x + ee[i, :] + ee[j, :], *args, **kwargs) -
                              g[i] - g[j] + f0) / hess[j, i]
                hess[j, i] = hess[i, j]
        return hess

    def _backward(self, f, x, h, *args, **kwargs):
        return self._forward(f, x, -h, *args, **kwargs)


def main():
    import statsmodels.api as sm

    data = sm.datasets.spector.load()
    data.exog = sm.add_constant(data.exog, prepend=False)
    mod = sm.Probit(data.endog, data.exog)
    _res = mod.fit(method="newton")
    _test_params = [1, 0.25, 1.4, -7]
    _llf = mod.loglike
    _score = mod.score
    _hess = mod.hessian

    def fun(beta, x):
        return np.dot(x, beta).sum(0)

    def fun1(beta, y, x):
        # print(beta.shape, x.shape)
        xb = np.dot(x, beta)
        return (y - xb) ** 2  # (xb-xb.mean(0))**2

    def fun2(beta, y, x):
        # print(beta.shape, x.shape)
        return fun1(beta, y, x).sum(0)

    nobs = 200
    x = np.random.randn(nobs, 3)

    # xk = np.array([1, 2, 3])
    xk = np.array([1., 1., 1.])
    # xk = np.zeros(3)
    beta = xk
    y = np.dot(x, beta) + 0.1 * np.random.randn(nobs)
    xk = np.dot(np.linalg.pinv(x), y)

    epsilon = 1e-6
    args = (y, x)
    from scipy import optimize
    _xfmin = optimize.fmin(fun2, (0, 0, 0), args)  # @UndefinedVariable
    # print(approx_fprime((1, 2, 3), fun, steps, x))
    jac = Gradient(fun1, epsilon, method='forward')(xk, *args)
    jacmin = Gradient(fun1, -epsilon, method='forward')(xk, *args)
    # print(jac)
    print(jac.sum(0))
    print('\nnp.dot(jac.T, jac)')
    print(np.dot(jac.T, jac))
    print('\n2*np.dot(x.T, x)')
    print(2 * np.dot(x.T, x))
    jac2 = (jac + jacmin) / 2.
    print(np.dot(jac2.T, jac2))

    # he = approx_hess(xk,fun2,steps,*args)
    print(Hessian(fun2, 1e-3, method='central2')(xk, *args))
    he = Hessian(fun2, method='central2')(xk, *args)
    print('hessfd')
    print(he)
    print('base_step =', None)
    print(he[0] - 2 * np.dot(x.T, x))

    for eps in [1e-3, 1e-4, 1e-5, 1e-6]:
        print('eps =', eps)
        print(Hessian(fun2, eps, method='central2')(xk, *args) -
              2 * np.dot(x.T, x))

    hcs2 = Hessian(fun2, method='complex')(xk, *args)
    print('hcs2')
    print(hcs2 - 2 * np.dot(x.T, x))

    hfd3 = Hessian(fun2, method='central')(xk, *args)
    print('hfd3')
    print(hfd3 - 2 * np.dot(x.T, x))

    hfi = []
    epsi = np.array([1e-1, 1e-2, 1e-3, 1e-4, 1e-5, 1e-6]) * 10.
    for eps in epsi:
        h = eps * np.maximum(np.log1p(np.abs(xk)), 0.1)
        hfi.append(Hessian(fun2, h, method='complex')(xk, *args))
        print('hfi, eps =', eps)
        print(hfi[-1] - 2 * np.dot(x.T, x))

    import numdifftools as nd
    print('Dea3')
    err = 1000 * np.ones(hfi[0].shape)
    val = np.zeros(err.shape)
    errt = []
    for i in range(len(hfi) - 2):
        tval, terr = nd.dea3(hfi[i], hfi[i + 1], hfi[i + 2])
        errt.append(terr)
        k = np.flatnonzero(terr < err)
        if k.size > 0:
            np.put(val, k, tval.flat[k])
            np.put(err, k, terr.flat[k])
    print(val - 2 * np.dot(x.T, x))
    print(err)
    erri = [v.max() for v in errt]

    plt.loglog(epsi[1:-1], erri)
    plt.show('hold')
    hnd = nd.Hessian(lambda a: fun2(a, y, x))
    hessnd = hnd(xk)
    print('numdiff')
    print(hessnd - 2 * np.dot(x.T, x))
    # assert_almost_equal(hessnd, he[0])
    gnd = nd.Gradient(lambda a: fun2(a, y, x))
    _gradnd = gnd(xk)

    print(Derivative(np.cosh)(0))
    print(nd.Derivative(np.cosh)(0))


def _get_test_function(fun_name, n=1):
    sinh, cosh, tanh = np.sinh, np.cosh, np.tanh
    f_dic = dict(exp=(np.exp, np.exp, np.exp, np.exp),
                 cos=(np.cos, lambda x: -np.sin(x),
                      lambda x: -np.cos(x),
                      lambda x: np.sin(x),
                      lambda x: np.cos(x)),
                 tanh=(tanh,
                       lambda x: 1. / cosh(x) ** 2,
                       lambda x: -2 * sinh(x) / cosh(x) ** 3,
                       lambda x: 2. * (3 * tanh(x) ** 2 - 1) / cosh(x) ** 2,
                       lambda x: (6 + 4 * sinh(x) *
                                  (cosh(x) - 3 * tanh(x))) / cosh(x) ** 4),
                 log=(np.log,
                      lambda x: 1. / x,
                      lambda x: -1. / x ** 2,
                      lambda x: 2. / x ** 3,
                      lambda x: -6. / x ** 4),
                 sqrt=(np.sqrt,
                       lambda x: 0.5/np.sqrt(x),
                       lambda x: -0.25/x**(1.5),
                       lambda x: 1.5*0.25/x**(1.5),
                       lambda x: -2.5*1.5*0.25/x**(2.5)),
                 inv=(lambda x: 1. / x,
                      lambda x: -1. / x ** 2,
                      lambda x: 2. / x ** 3,
                      lambda x: -6. / x ** 4,
                      lambda x: 24. / x ** 5))
    funs = f_dic.get(fun_name)
    fun0 = funs[0]
    dfun = funs[n]
    return fun0, dfun


def _example2(x=0.0001, fun_name='inv', epsilon=None, method='central',
              scale=None, n=1):
    fun0, dfun = _get_test_function(fun_name, n)

    fd = NDerivative(fun0, steps=epsilon, method=method, n=n, order=5)
    t = []
    scales = np.linspace(1, 12)
    for scale in scales:
        fd.scale = scale
        t.append(fd(x))
    t = np.array(t)
    tt = dfun(x)
    plt.semilogy(scales, np.abs(t - tt) / (np.abs(tt) + 1e-17) + 1e-17)
    plt.vlines(fd.default_scale(fd.method, n), 1e-16, 1)
    plt.show('hold')


def _example(x=0.0001, fun_name='inv', epsilon=None, method='central',
             scale=None):
    '''
    '''
    fun0, dfun = _get_test_function(fun_name)

    h = _default_base_step(x, scale=2, epsilon=None)  # 1e-4

    fd = Derivative(fun0, steps=epsilon, method=method, scale=scale,
                    full_output=True)

    t, res = fd(x)

    txt = (' (f(x+h)-f(x))/h = %g\n' %
           ((fun0(x + h) - fun0(x)) / h))
    deltas = np.array([h for h in epsilon(x, fd.scale)])

    print((txt +
           '      true df(x) = %20.15g\n' +
           ' estimated df(x) = %20.15g\n' +
           ' true err = %g\n err estimate = %g\n relative err = %g\n'
           ' delta = %g\n') % (dfun(x), t, dfun(x) - t,
                               res.error_estimate,
                               res.error_estimate / t,
                               deltas.flat[res.index]))
    # plt.show('hold')


def test_docstrings():
    import doctest
    doctest.testmod(optionflags=doctest.NORMALIZE_WHITESPACE)


if __name__ == '__main__':  # pragma : no cover
    # test_docstrings()
    # main()
    epsilon = StepsGenerator(num_steps=1, step_ratio=4, offset=0,
                             use_exact_steps=False)
    # epsilon = StepsGenerator2(num_steps=5)
    _example2(x=1, fun_name='cos', epsilon=epsilon, method='central',
              scale=None, n=4)
    #     import nxs
#     steps = StepsGenerator(num_steps=7)
#     d = Derivative(np.cos, method='central', steps=steps,
#                    full_output=True)
#     print(d([0, 1e5*np.pi*2]))
#     print(d(1e10*np.pi*2))
