# generic libraries
import numpy as np
from numpy.lib.stride_tricks import as_strided

# image processing libraries
from scipy import ndimage, signal
from skimage.filters import threshold_otsu
from sklearn.cluster import MeanShift, estimate_bandwidth

from ..generic.filtering_statistical import make_2D_Gaussian
from ..generic.handler_im import rotated_sobel, diff_compass

from ..processing.matching_tools_frequency_filters import perdecomp

def enhance_shadows(Shw, method, **kwargs):
    """ Given a specific method, employ shadow transform

    Parameters
    ----------
    Shw : np.array, size=(m,n), dtype={float,integer}
        array with intensities of shading and shadowing
    method : {‘mean’,’kuwahara’,’median’,’otsu’,'anistropic'}
        method name to be implemented,can be one of the following:

            * 'mean' : mean shift filter
            * 'kuwahara' : kuwahara filter
            * 'median' : iterative median filter
            * 'anistropic' : anistropic diffusion filter

    Returns
    -------
    M : np.array, size=(m,n), dtype={float,integer}
        shadow enhanced image, done through the given method

    See Also
    --------
    mean_shift_filter, kuwahara_filter, iterative_median_filter,
    anistropic_diffusion_scalar
    """
    if method in ('mean', 'mean-shift'):
        quantile=0.1 if kwargs.get('quantile')==None else kwargs.get('quantile')
        M = mean_shift_filter(Shw, quantile=quantile)
    elif method in ('kuwahara'):
        tsize=5 if kwargs.get('tsize')==None else kwargs.get('tsize')
        M = kuwahara_filter(Shw, tsize=tsize)
    elif method in ('median'):
        tsize=5 if kwargs.get('tsize')==None else kwargs.get('tsize')
        iter=50 if kwargs.get('loop')==None else kwargs.get('loop')
        M = iterative_median_filter(Shw,tsize=tsize, loop=iter)
    elif method in ('anistropic', 'anistropic-diffusion'):
        iter = 10 if kwargs.get('iter') == None else kwargs.get('iter')
        K = .15 if kwargs.get('K') == None else kwargs.get('K')
        s = .25 if kwargs.get('s') == None else kwargs.get('s')
        n = 4 if kwargs.get('n') == None else kwargs.get('n')
        M = anistropic_diffusion_scalar(Shw, iter=iter, K=K, s=s, n=n)
    elif method in ('L0', 'L0smoothing'):
        lamb = 2E-2 if kwargs.get('lamb') == None else kwargs.get('lamb')
        kappa = 2. if kwargs.get('kappa') == None else kwargs.get('kappa')
        M = L0_smoothing(Shw, lamb=lamb, kappa=kappa)
    else:
        assert 1==2, 'please provide a correct method'
    return M

# functions to spatially enhance the shadow image
def mean_shift_filter(I, quantile=0.1):
    """ Transform intensity to more clustered intensity, through mean-shift

    Parameters
    ----------
    I : np.array, size=(m,n), dtype=float
        array with intensity values
    quantile : float, range=0...1

    Returns
    -------
    labels : np.array, size=(m,n), dtype=integer
        array with numbered labels
    """
    bw = estimate_bandwidth(I, quantile=quantile, n_samples=I.shape[1])
    ms = MeanShift(bandwidth=bw, bin_seeding=True)
    ms.fit(I.reshape(-1,1))

    labels = np.reshape(ms.labels_, I.shape)
    return labels

def kuwahara(buffer):
    d = int(np.sqrt(len(buffer))) # assuming square kernel
    d_sub = int(((d - 1) // 2) + 1)

    buffer = np.reshape(buffer, (d, d))
    r_a, r_b = buffer[:-d_sub+1, :-d_sub+1], buffer[+d_sub-1:, :-d_sub+1]
    r_c, r_d = buffer[:-d_sub+1, +d_sub-1:], buffer[+d_sub-1:, +d_sub-1:]

    var_abcd = np.array([np.var(r_a), np.var(r_b),
                         np.var(r_c), np.var(r_d)])
    bar_abcd = np.array([np.mean(r_a), np.mean(r_b),
                         np.mean(r_c), np.mean(r_d)])
    idx_abcd = np.argmin(var_abcd)
    return bar_abcd[idx_abcd]

def kuwahara_strided(buffer): # todo: gives error, but it might run faster...?
    d = int(np.sqrt(len(buffer)))  # assuming square kernel
    if d == 5:
        strides = (10,2,5,1)
        shape = (2,2,3,3)
    elif d == 3:
        strides = (3,1,3,1)
        shape = (2,2,2,2)
    abcd = as_strided(np.reshape(buffer, (d, d)),
                      shape=shape, strides=strides)
    var_abcd = np.var(abcd, (2, 3))
    bar_abcd = np.mean(abcd, (2, 3))
    idx_abcd = np.argmin(var_abcd)
    return bar_abcd[idx_abcd]

def kuwahara_filter(I, tsize=5):
    """ Transform intensity to more clustered intensity

    Parameters
    ----------
    I : np.array, size=(m,n), dtype=float
        array with intensity values
    tsize : integer, {x ∈ ℕ | x ≥ 1}
        dimension of the kernel

    Returns
    -------
    I_new : np.array, size=(m,n), dtype=float

    Notes
    -----
    The template is subdivided into four blocks, where the sampled mean and
    standard deviation are calculated. Then mean of the block with the lowest
    variance is assigned to the central pixel. The configuration of the blocks
    look like:

        .. code-block:: text

          ┌-----┬-┬-----┐ ^
          |  A  | |  B  | |
          ├-----┼-┼-----┤ | tsize
          ├-----┼-┼-----┤ |
          |  C  | |  D  | |
          └-----┴-┴-----┘ v

    See Also
    --------
    iterative_median_filter
    """
    assert np.remainder(tsize,1)==0, ('please provide square kernel')
    assert np.remainder(tsize-1,2)==0, ('kernel dimension should be odd')
    assert tsize>=3, ('kernel should be big enough')

    #if (tsize==3) or (tsize==5): # todo
    #    I_new = ndimage.generic_filter(I, kuwahara_strided, size=(tsize,tsize))
    #else:
    I_new = ndimage.generic_filter(I, kuwahara, size=(tsize,tsize))
    return I_new

def iterative_median_filter(I, tsize=5, loop=50):
    """ Transform intensity to more clustered intensity, through iterative
    filtering with a median operation

    Parameters
    ----------
    I : np.array, size=(m,n), dtype=float
        array with intensity values
    tsize : integer, {x ∈ ℕ | x ≥ 1}
        dimension of the kernel
    loop : integer, {x ∈ ℕ | x ≥ 0}
        amount of iterations

    Returns
    -------
    I_new : np.array, size=(m,n), dtype=float
        array with stark edges

    See Also
    --------
    kuwahara_filter
    """
    for i in range(loop):
        I = ndimage.median_filter(I, size=tsize)
    return I

def selective_blur_func(C, t_size):
    # decompose arrays, these seem to alternate....
    C_col = C.reshape(t_size[0],t_size[1],2)
    if np.any(np.sign(C[::2])==-1):
        M, I = -1*C_col[:,:,0].flatten(), C_col[:,:,1].flatten()
    else: # redundant calculation, just ignore and exit
        return 0

    m_central = M[(t_size[0]*t_size[1])//2]
    i_central = I[(t_size[0]*t_size[1])//2]
    if m_central != 1: return i_central

    W = make_2D_Gaussian(t_size, fwhm=3).flatten()
    W /= np.sum(W)
    new_intensity = np.sum(W*I)
    return new_intensity

def fade_shadow_cast(Shw, az, t_size=9):
    """

    Parameters
    ----------
    Shw : np.array, size=(m,n)
        image with mask of shadows
    az : float, unit=degrees
        illumination orientation
    t_size : integer, {x ∈ ℕ | x ≥ 1}
        buffer size of the Gaussian blur

    Returns
    -------
    Shw : np.array, size=(m,n), dtype=float, range=0...1
        image with faded shadows on the occluding end
    """
    kernel_az = rotated_sobel(az, size=5, indexing='xy')

    new_dims = []
    for original_length, new_length in zip(kernel_az.shape, (t_size, t_size)):
        new_dims.append(np.linspace(0, original_length - 1, new_length))

    coords = np.meshgrid(*new_dims, indexing='ij')
    kernel_az = ndimage.map_coordinates(kernel_az, coords)

    W_f = ndimage.convolve(Shw.astype(np.float64), kernel_az)
    M_f = np.logical_and(W_f > 0.001,
                         ~(W_f < 0.001))# cast ridges

    Combo = np.dstack((Shw, -1.*(M_f.astype(np.float64))))

    S_b = ndimage.generic_filter(Combo, selective_blur_func,
                               footprint=np.ones((t_size, t_size, 2)),
                               mode='mirror', cval=np.nan,
                               extra_keywords = {'t_size': (t_size, t_size)}
                               )
    S_b = S_b[...,0]
    Shf = np.copy(Shw).astype(np.float64)
    Shf[M_f] = S_b[M_f]
    return Shf

def diffusion_strength_1(I,K):
    """ first diffusion function, proposed by [1], when a complex array is
    provided the absolute magnitude is used, following [2]

    Parameters
    ----------
    I : np.array, size=(m,n), dtype={float,complex}, ndim={2,3}
        array with intensities
    K : float
        parameter based upon the noise level

    Returns
    -------
    g : np.array, size=(m,n), dtype=float
        array with diffusion parameters

    References
    ----------
    .. [1] Perona & Malik "Scale space and edge detection using anisotropic
       diffusion" Proceedings of the IEEE workshop on computer vision, pp.16-22,
       1987
    .. [2] Gerig et al. "Nonlinear anisotropic filtering of MRI data" IEEE
       transactions on medical imaging, vol.11(2), pp.221-232, 1992
    """
    # admin
    if np.iscomplexobj(I): # support complex input
        I_abs = np.abs(I)
        g_1 = np.exp(-1 * np.divide(np.abs(I),K)**2)
    elif I.ndim==3: # support multispectral input
        I_sum = np.sum(I**2,axis=2)
        I_abs = np.sqrt(I_sum,
                        out=np.zeros_like(I_sum), where=I_sum!=0)
    else:
        I_abs = I

    # caluculation
    g_1 = np.exp(-1 * np.divide(I_abs, K) ** 2)
    return g_1

def diffusion_strength_2(I,K):
    """ second diffusion function, proposed by [1], when a complex array is
    provided the absolute magnitude is used, following [2]

    Parameters
    ----------
    I : np.array, size=(m,n), dtype={float,complex}
        array with intensities
    K : float
        parameter based upon the noise level

    Returns
    -------
    g : np.array, size=(m,n), dtype=float
        array with diffusion parameters

    References
    ----------
    .. [1] Perona & Malik "Scale space and edge detection using anisotropic
       diffusion" Proceedings of the IEEE workshop on computer vision, pp.16-22,
       1987
    .. [2] Gerig et al. "Nonlinear anisotropic filtering of MRI data" IEEE
       transactions on medical imaging, vol.11(2), pp.221-232, 1992
    """
    if np.iscomplexobj(I):
        I_abs = np.abs(I)
        denom = (1 + np.divide(np.abs(I), K) ** 2)
    elif I.ndim==3: # support multispectral input
        I_sum = np.sum(I**2,axis=2)
        I_abs = np.sqrt(I_sum,
                        out=np.zeros_like(I_sum), where=I_sum!=0)
    else:
        I_abs = I
    # calculation
    denom = (1 + np.divide(I_abs,K)**2)
    g_2 = np.divide(1, denom, where=denom!=0)
    return g_2

def anistropic_diffusion_scalar(I, iter=10, K=.15, s=.25, n=4):
    """ non-linear anistropic diffusion filter of a scalar field

    Parameters
    ----------
    I : np.array, size=(m,n), dtype={float,complex}, ndim={2,3}
        intensity array
    iter : integer, {x ∈ ℕ | x ≥ 0}
        amount of iterations
    K : float, default=.15
        parameter based upon the noise level
    s : float, default=.25
        parameter for the integration constant
    n : {4,8}
        amount of neighbors used

    Returns
    -------
    I : np.array, size=(m,n)

    References
    ----------
    .. [1] Perona & Malik "Scale space and edge detection using anisotropic
       diffusion" Proceedings of the IEEE workshop on computer vision, pp.16-22,
       1987
    .. [2] Gerig et al. "Nonlinear anisotropic filtering of MRI data" IEEE
       transactions on medical imaging, vol.11(2), pp.221-232, 1992
    """
    # admin
    I_new = np.copy(I)
    multispec = True if I.ndim==3 else False
    if multispec: b = I.shape[2]
    if n != 4: delta_d = np.sqrt(2)
    s = np.minimum(s,1/n) # see Appendix A in [2]

    # processing
    for i in range(iter):
        I_u = diff_compass(I_new,direction='n')
        I_d = diff_compass(I_new,direction='s')
        I_r = diff_compass(I_new,direction='e')
        I_l = diff_compass(I_new,direction='w')
        if not multispec:
            I_update = (diffusion_strength_1(I_u, K) * I_u +
                        diffusion_strength_1(I_d, K) * I_d +
                        diffusion_strength_1(I_r, K) * I_r +
                        diffusion_strength_1(I_l, K) * I_l
                        )
        else:
            I_update = (np.tile(diffusion_strength_1(I_u, K)[:, :, np.newaxis],
                                (1, 1, b)) * I_u +
                        np.tile(diffusion_strength_1(I_r, K)[:, :, np.newaxis],
                                (1, 1, b)) * I_r +
                        np.tile(diffusion_strength_1(I_d, K)[:, :, np.newaxis],
                                (1, 1, b)) * I_d +
                        np.tile(diffusion_strength_1(I_l, K)[:, :, np.newaxis],
                                (1, 1, b)) * I_l)
        del I_u, I_d, I_r, I_l

        if n>4:
            # alternate with the cross-domain, following the approach of [2]
            I_ur = diff_compass(I_new, direction='n') / delta_d
            I_lr = diff_compass(I_new, direction='s') / delta_d
            I_ll = diff_compass(I_new, direction='e') / delta_d
            I_ul = diff_compass(I_new, direction='w') / delta_d

            if not multispec:
                I_xtra = (diffusion_strength_1(I_ur, K) * I_ur +
                          diffusion_strength_1(I_lr, K) * I_lr +
                          diffusion_strength_1(I_ll, K) * I_ll +
                          diffusion_strength_1(I_ul, K) * I_ul)
            else: # extent the diffusion parameter to all bands
                I_xtra = (np.tile(diffusion_strength_1(I_ur,K)[:,:,np.newaxis],
                                  (1,1,b)) * I_ur +
                          np.tile(diffusion_strength_1(I_lr,K)[:,:,np.newaxis],
                                  (1,1,b)) * I_lr +
                          np.tile(diffusion_strength_1(I_ll,K)[:,:,np.newaxis],
                                  (1,1,b)) * I_ll +
                          np.tile(diffusion_strength_1(I_ul,K)[:,:,np.newaxis],
                                  (1,1,b)) * I_ul)
            I_update += I_xtra
        I_new[1:-1,1:-1] += s*I_update
    return I_new

def psf2otf(psf, dim):
    m,n = psf.shape[0], psf.shape[1]

    new_psf = np.zeros(dim)
    new_psf[:m, :n] = psf[:, :]

    new_psf = np.roll(new_psf, -dim[0]//2, axis=0)
    new_psf = np.roll(new_psf, -dim[1]//2, axis=1)
    otf = np.fft.fft2(new_psf)
    return otf

def L0_smoothing(I, lamb=2E-2, kappa=2., beta_max=1E5):
    """

    Parameters
    ----------
    I : numpy.array, size={(m,n), (m,n,b)}, dtype=float
        grid with intensity values
    lamb : float, default=.002
    kappa : float, default=2.
    beta_max : float, default=10000

    Returns
    -------
    I : numpy.array, size={(m,n), (m,n,b)}, dtype=float
        modified intensity image

    References
    ----------
    .. [1] Xu et al. "Image smoothing via L0 gradient minimization" ACM
           transactions on graphics, 2011.
    """
    m,n = I.shape[:2]
    b=1 if I.ndim==2 else I.shape[2]

    dx,dy = np.array([[+1, -1]]), np.array([[+1], [-1]])
    dx_F,dy_F = psf2otf(dx,(m,n)), psf2otf(dy,(m,n))

    I = perdecomp(I)[0]
    N_1 = np.fft.fft2(I)
    D_2 = np.abs(dx_F) ** 2 + np.abs(dy_F) ** 2

    if b>1:
        dx, dy = np.tile(dx[..., np.newaxis], (1,1,b)), \
                 np.tile(dy[..., np.newaxis], (1,1,b))
        D_2 = np.tile(D_2[...,np.newaxis], (1,1,b))

    beta = 2*lamb
    while beta < beta_max:
        D_1 = 1 + beta*D_2

        h = np.roll(signal.fftconvolve(I,dx, mode='same'), -1, axis=1)
        v = np.roll(signal.fftconvolve(I, dy, mode='same'), -1, axis=0)

        t = (h**2 + v**2)<(lamb/beta)
        np.putmask(h, t, 0)
        np.putmask(v, t, 0)

        if b==1:
            N_2 =  np.concatenate((np.array(h[:,-1]-h[:,0], ndmin=2).T,
                                   -np.diff(h,1,1)), axis=1)
            N_2 += np.concatenate((np.array(v[-1,...]-v[0,...], ndmin=2),
                                   -np.diff(v,1,0)), axis=0)
        else:
            N_2 = np.concatenate((np.array(h[:,-1,:]-h[:,0,:], ndmin=3
                                           ).transpose((1, 0, 2)),
                                  -np.diff(h, 1, 1)), axis=1)
            N_2 += np.concatenate((np.array(v[-1,...]-v[0,...], ndmin=3),
                                   -np.diff(v,1,0)), axis=0)
            N_2 = np.tile(np.sum(N_2, axis=2)[...,np.newaxis], (1,1,b))
        I_F = np.divide( N_1 + beta*np.fft.fft2(N_2) ,D_1)
        I = np.real(np.fft.ifft2(I_F))
        beta *= kappa
    return I