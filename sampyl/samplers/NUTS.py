from __future__ import division

from ..core import np
from .base import Sampler
from .hamiltonian import leapfrog, energy, initial_momentum


class NUTS(Sampler):
    def __init__(self, logp, start,
                 step_size=0.25,
                 adapt_steps=100,
                 Emax=1000.,
                 target_accept=0.65,
                 gamma=0.05,
                 k=0.75,
                 t0=10.,
                 **kwargs):

        """ No-U-Turn sampler (Hoffman & Gelman, 2014) for sampling from a
            probability distribution defined by a log P(theta) function.

            For technical details, see the paper:
            http://www.stat.columbia.edu/~gelman/research/published/nuts.pdf

            Arguments
            ----------
            logp: function
                log P(X) function for sampling distribution
            start: dict
                Dictionary of starting state for the sampler. Should have one
                element for each argument of logp. So, if logp = f(x, y), then
                start = {'x': x_start, 'y': y_start}

            Keyword Arguments
            -----------------
            grad_logp: function or list of functions
                Functions that calculate grad log P(theta). Pass functions
                here if you don't want to use autograd for the gradients. If
                logp has multiple parameters, grad_logp must be a list of
                gradient functions w.r.t. each parameter in logp.
            scale: dict
                Same format as start. Scaling for initial momentum in 
                Hamiltonian step.
            step_size: float
                Initial step size for the deterministic proposals.
            adapt_steps: int
                Number of steps used for adapting the step size to achieve a
                target acceptance rate
            Emax: float
                Maximum energy
            target_accept: float
                Target acceptance rate
            gamma: float
            k: float
                Scales the speed of adaptation
            t0: float
                Slows initial adaptation

        """
        
        super(NUTS, self).__init__(logp, start, **kwargs)

        self.step_size = step_size / len(self.state.tovector())**(1/4.)
        self.adapt_steps = adapt_steps
        self.Emax = Emax
        self.target_accept = target_accept
        self.gamma = gamma
        self.k = k
        self.t0 = t0

        self.Hbar = 0.
        self.ebar = 1.
        self.mu = np.log(self.step_size*10)

    def step(self):

        H = self.logp
        dH = self.grad_logp
        x = self.state
        r0 = initial_momentum(x, self.scale)
        u = np.random.uniform()
        e = self.step_size
        xn, xp, rn, rp, y = x, x, r0, r0, x
        j, n, s = 0, 1, 1

        while s == 1:
            v = bern(0.5)*2 - 1
            if v == -1:
                xn, rn, _, _, x1, n1, s1, a, na = buildtree(xn, rn, u, v, j, e, x, r0,
                                                            H, dH, self.Emax)
            else:
                _, _, xp, rp, x1, n1, s1, a, na = buildtree(xp, rp, u, v, j, e, x, r0,
                                                            H, dH, self.Emax)

            if s1 == 1 and bern(np.min(np.array([1, n1/n]))):
                y = x1

            dx = (xp - xn).tovector()
            s = s1 * (np.dot(dx, rn.tovector()) >= 0) * \
                     (np.dot(dx, rp.tovector()) >= 0)
            n = n + n1
            j = j + 1

        if self._sampled >= self.adapt_steps:
            self.step_size = self.ebar
        else:
            # Adapt step size
            m = self._sampled + 1
            w = 1./(m + self.t0)
            self.Hbar = (1 - w)*self.Hbar + w*(self.target_accept - a/na)
            log_e = self.mu - (m**.5/self.gamma)*self.Hbar
            self.step_size = np.exp(log_e)
            z = m**(-self.k)
            self.ebar = np.exp(z*log_e + (1 - z)*np.log(self.ebar))

        self.state = y
        self._sampled += 1

        return y


def bern(p):
    return np.random.uniform() < p


def buildtree(x, r, u, v, j, e, x0, r0, H, dH, Emax):
    if j == 0:
        x1, r1 = leapfrog(x, r, v*e, dH)
        E = energy(H, x1, r1)
        E0 = energy(H, x0, r0)
        dE = E - E0

        n1 = (np.log(u) - dE <= 0)
        s1 = (np.log(u) - dE < Emax)
        return x1, r1, x1, r1, x1, n1, s1, np.min(np.array([1, np.exp(dE)])), 1
    else:
        xn, rn, xp, rp, x1, n1, s1, a1, na1 = \
            buildtree(x, r, u, v, j-1, e, x0, r0, H, dH, Emax)
        if s1 == 1:
            if v == -1:
                xn, rn, _, _, x2, n2, s2, a2, na2 = \
                    buildtree(xn, rn, u, v, j-1, e, x0, r0, H, dH, Emax)
            else:
                _, _, xp, rp, x2, n2, s2, a2, na2 = \
                    buildtree(xp, rp, u, v, j-1, e, x0, r0, H, dH, Emax)
            if bern(n2/max(n1 + n2, 1.)):
                x1 = x2

            a1 = a1 + a2
            na1 = na1 + na2

            dx = (xp - xn).tovector()
            s1 = s2 * (np.dot(dx, rn.tovector()) >= 0) * \
                      (np.dot(dx, rp.tovector()) >= 0)
            n1 = n1 + n2
        return xn, rn, xp, rp, x1, n1, s1, a1, na1
        