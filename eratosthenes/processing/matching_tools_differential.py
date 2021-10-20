# general libraries
import warnings
import numpy as np

# image processing libraries
from scipy import ndimage, interpolate

from ..preprocessing.image_transforms import mat_to_gray
from ..generic.mapping_tools import pol2cart
from ..generic.filtering_statistical import make_2D_Gaussian
from ..generic.handler_im import get_grad_filters

# spatial sub-pixel allignment functions
def simple_optical_flow(I1, I2, window_size, sampleI, sampleJ, \
                        tau=1e-2, sigma=0.):  # processing
    """ displacement estimation through optical flow

    Parameters
    ----------    
    I1 : np.array, size=(m,n)
        array with intensities
    I2 : np.array, size=(m,n)
        array with intensities
    window_size: integer
        kernel size of the neighborhood
    sampleI: np.array, size=(k,l)     
        grid with image coordinates, its vertical coordinate in a pixel system
    sampleJ: np.array, size=(k,l)     
        grid with image coordinates, its horizontical coordinate
    sigma: float             
        smoothness for gaussian image blur        
        
    Returns
    -------
    Ugrd : np.array, size=(k,l)
        vertical displacement estimate, in "ij"-coordinate system
    Vgrd : np.array, size=(k,l)
        vertical displacement estimate, in "ij"-coordinate system
    Ueig : np.array, size=(k,l)
        eigenvalue of system of equation for vertical estimate      
    Veig : np.array, size=(k,l)
        eigenvalue of system of equation for horizontal estimate   
        
    See Also
    --------
    affine_optical_flow  
    
    Notes
    ----- 
    This is a fast implementation using the direct surrounding to solve the 
    following problem:

        .. math:: \frac{\partial I}{\partial t} = 
        \frac{\partial I}{\partial x} \cdot \frac{\partial x}{\partial t} + 
        \frac{\partial I}{\partial y} \cdot \frac{\partial y}{\partial t}
        
    Where :math:`\frac{\partial I}{\partial x}` are spatial derivatives, and
    :math:`\frac{\partial I}{\partial t}` the temporal change, while 
    :math:`\frac{\partial x}{\partial t}` and 
    :math:`\frac{\partial y}{\partial t}` are the parameters of interest.

    Two different coordinate system are used here: 
        
        .. code-block:: text
    
            o____j                          y  map(x, y)
            |                               |
            |                               |
            i image(i, j)                   o_____x
          pixel coordinate frame        metric coordinate frame
    
    References
    ----------    
    .. [1] Lucas & Kanade, "An iterative image registration technique with an 
       application to stereo vision", Proceedings of 7th international joint 
       conference on artificial intelligence, 1981.
    """ 
 
    # check and initialize
    if isinstance(sampleI, int):
        sampleI = np.array([sampleI])
    if isinstance(sampleJ, int):
        sampleJ = np.array([sampleJ])
    
    # if data range is bigger than 1, transform
    if np.ptp(I1.flatten())>1: 
        I1 = mat_to_gray(I1)
    if np.ptp(I1.flatten())>1:
        I2 = mat_to_gray(I2)
    
    # smooth the image, so derivatives are not so steep
    if sigma!=0:
        I1 = ndimage.gaussian_filter(I1, sigma=sigma)
        I2 = ndimage.gaussian_filter(I2, sigma=sigma)
    
    kernel_x = np.array(
        [[-1., 1.],
         [-1., 1.]]
    ) * .25
    kernel_t = np.array(
        [[1., 1.],
         [1., 1.]]
    ) * .25

    fx = ndimage.convolve(I1, kernel_x)
    fy = ndimage.convolve(I1, np.flip(np.transpose(kernel_x), axis=0))
    ft = ndimage.convolve(I2, kernel_t) + ndimage.convolve(I1, -kernel_t)

    # grid or single estimation
    if sampleI.ndim>1:
        Ugrd = np.zeros((len(sampleI), len(sampleJ)))
        Vgrd = np.zeros_like(Ugrd), 
        Ueig,Veig = np.zeros_like(Ugrd), np.zeros_like(Ugrd)
    else:
        Ugrd,Vgrd,Ueig,Veig = 0,0,0,0
    
    # window_size should be odd
    radius = np.floor(window_size / 2).astype('int')  
    for iIdx in np.arange(sampleI.size):
        iIm = sampleI.flat[iIdx]
        jIm = sampleJ.flat[iIdx]
        
        if sampleI.ndim>1:
            (iGrd, jGrd) = np.unravel_index(iIdx, sampleI.shape) 
        
        # get templates
        Ix = fx[iIm - radius:iIm + radius + 1,
                jIm - radius:jIm + radius + 1].flatten()
        Iy = fy[iIm - radius:iIm + radius + 1,
                jIm - radius:jIm + radius + 1].flatten()
        It = ft[iIm - radius:iIm + radius + 1,
                jIm - radius:jIm + radius + 1].flatten()

        # look if variation is present
        if np.std(It) != 0:
            b = np.reshape(It, (It.shape[0], 1))  # get b here
            A = np.vstack((Ix, Iy)).T  # get A here
            
            # caluclate eigenvalues to see directional contrast distribution
            epsilon = np.linalg.eigvals(np.matmul(A.T, A))
            nu = np.matmul(np.linalg.pinv(A), -b)  # get velocity here
            
            if sampleI.ndim>1:
                Ugrd[iGrd,jGrd], Vgrd[iGrd,jGrd] = nu[0][0],nu[1][0]
                Ueig[iGrd,jGrd], Veig[iGrd,jGrd] = epsilon[0],epsilon[1]
            else:
                Ugrd, Vgrd = nu[1][0], nu[0][0]
                Ueig, Veig = epsilon[1], epsilon[0]

    return Ugrd, Vgrd, Ueig, Veig

def affine_optical_flow(I1, I2, model='Affine', iteration=15):
    """
    displacement estimation through optical flow
    following Lucas & Kanade 1981 with an affine model
    
    reference:
              
    :param I1:        NP.ARRAY (_,_)
        image with intensities
    :param I2:        NP.ARRAY (_,_)
        image with intensities
    :param model:     STRING
           :options :  Affine - affine and translation
                       Rotation - TODO
    :param iteration: INTEGER
        number of iterations used
                     
    :return u:        FLOAT
        displacement estimate
    :return v:        FLOAT     
        displacement estimate                    
    """

    (kernel_j,_) = get_grad_filters('kroon')

    kernel_t = np.array(
        [[1., 1., 1.],
         [1., 2., 1.],
         [1., 1., 1.]]
    ) / 10
    
    # smooth to not have very sharp derivatives
    I1 = ndimage.convolve(I1, make_2D_Gaussian((3,3),fwhm=3))
    I2 = ndimage.convolve(I2, make_2D_Gaussian((3,3),fwhm=3))
    
    # calculate spatial and temporal derivatives
    I_dj = ndimage.convolve(I1, kernel_j)
    I_di = ndimage.convolve(I1, np.flip(np.transpose(kernel_j), axis=0))

    # create local coordinate grid
    (mI,nI) = I1.shape
    mnI = I1.size
    (grd_i,grd_j) = np.meshgrid(np.linspace(-(mI-1)/2, +(mI-1)/2, mI), \
                                np.linspace(-(nI-1)/2, +(nI-1)/2, nI), \
                                indexing='ij')
    grd_j = np.flipud(grd_j)
    stk_ij = np.vstack( (grd_i.flatten(), grd_j.flatten()) ).T
    p = np.zeros((1,6), dtype=float)
    p_stack = np.zeros((iteration,6), dtype=float)
    res = np.zeros((iteration,1), dtype=float) # look at iteration evolution
    for i in np.arange(iteration):
        # affine transform
        Aff = np.array([[1, 0, 0], [0, 1, 0]]) + p.reshape(3,2).T
        grd_new = np.matmul(Aff,
                            np.vstack((stk_ij.T, 
                                       np.ones(mnI))))
        new_i = np.reshape(grd_new[0,:], (mI, nI))
        new_j = np.reshape(grd_new[1,:], (mI, nI))
        
        # construct new templates
        try:
            I2_new = interpolate.griddata(stk_ij, I2.flatten().T,
                                          (new_i,new_j), method='cubic')
        except:
            print('different number of values and points')
        I_di_new = interpolate.griddata(stk_ij, I_di.flatten().T,
                                        (new_i,new_j), method='cubic')
        I_dj_new = interpolate.griddata(stk_ij, I_dj.flatten().T,
                                        (new_i,new_j), method='cubic')

        # I_dt = ndimage.convolve(I2_new, kernel_t) + 
        #    ndimage.convolve(I1, -kernel_t)
        I_dt_new = I2_new - I1

        # compose Jacobian and Hessian
        dWdp = np.array([ \
                  I_di_new.flatten()*grd_i.flatten(),
                  I_dj_new.flatten()*grd_i.flatten(),
                  I_di_new.flatten()*grd_j.flatten(),
                  I_dj_new.flatten()*grd_j.flatten(),
                  I_di_new.flatten(),
                  I_dj_new.flatten()])

        # remove data outside the template
        A, y = dWdp.T, I_dt_new.flatten()
        IN = ~(np.any(np.isnan(A), axis=1) | np.isnan(y))
        
        A = A[IN,:] 
        y = y[~np.isnan(y)]
        
        #(dp,res[i]) = least_squares(A, y, mode='andrews', iterations=3) 
        if y.size>=6: # structure should not become ill-posed
            try:
                (dp,res[i],_,_) = np.linalg.lstsq(A, y, rcond=None)#[0]
            except ValueError:
                pass #print('something wrong?')
        else:
            break
        p += dp
        p_stack[i,:] = p
    
    # only convergence is allowed 
    (up_idx,_) = np.where(np.sign(res-np.vstack(([1e3],res[:-1])))==1)
    if up_idx.size != 0:
        res = res[:up_idx[0]]
    
    if res.size == 0: # sometimes divergence occurs
        A = np.array([[1, 0], [0, 1]])
        u, v, snr = 0, 0, 0
    else:
        Aff = np.array([[1, 0, 0], [0, 1, 0]]) + \
            p_stack[np.argmin(res),:].reshape(3,2).T
        u, v = Aff[0,-1], Aff[1,-1]   
        A = np.linalg.inv(Aff[:,0:2]).T
        snr = np.min(res)
    return (u, v, A, snr)   

def hough_optical_flow(I1, I2, param_resol=100, sample_fraction=1):
    """ estimating optical flow through the Hough transform
    
    Parameters
    ----------
    I1 : np.array, size=(m,n,b), dtype=float, ndim=2
        first image array.
    I2 : np.array, size=(m,n,b), dtype=float, ndim=2
        second image array.

    Returns
    -------
    di,dj : float     
        sub-pixel displacement

    References
    ----------
    .. [1] Fennema & Thompson, "Velocity determination in scenes containing 
       several moving objects" Computer graphics and image processing, vol.9
       pp.301-317, 1979.
    .. [2] Guo & Lü, "Phase-shifting algorithm by use of Hough transform"
       Optics express vol.20(23) pp.26037-26049, 2012.
    """

    kernel_x,kernel_y = get_grad_filters('kroon')

    kernel_t = np.array(
        [[1., 1., 1.],
         [1., 2., 1.],
         [1., 1., 1.]]
    ) / 10
    
    # smooth to not have very sharp derivatives
    I1 = ndimage.convolve(I1, make_2D_Gaussian((3,3),fwhm=3))
    I2 = ndimage.convolve(I2, make_2D_Gaussian((3,3),fwhm=3))
        
    # calculate spatial and temporal derivatives
    I_dx = ndimage.convolve(I1, kernel_x)
    I_dy = ndimage.convolve(I1, kernel_y)
    I_dt = ndimage.convolve(I2, kernel_t) + ndimage.convolve(I1, -kernel_t)

    # create data
    abs_G = np.sqrt(I_dx**2 + I_dy**2)
    theta_G = np.arctan2(I_dx,I_dy)    

    rho = I_dt/abs_G

    # hough 
    sample_size = rho.size
    if sample_fraction>=1:
        idx = np.arange(0, sample_size)
    else: # sample random from collection
        idx = np.random.choice(sample_size, 
                               np.round(sample_size*sample_fraction).astype(np.int32), 
                               replace=False)  

    (u,v) = np.meshgrid(np.linspace(-1,+1, param_resol),\
                        np.linspace(-1,+1, param_resol))    
    vote = np.zeros((param_resol, param_resol), dtype=np.float32)

    for counter in idx:
        (idx_i,idx_j) = np.unravel_index(counter, rho.shape)
        diff = rho[idx_i,idx_j] - \
            u*np.cos(theta_G[idx_i,idx_j]) + \
            v*np.sin(theta_G[idx_i,idx_j])
        vote += 1/(1+np.abs(diff)) 
        
    ind = np.unravel_index(np.argmax(vote, axis=None), vote.shape)    
    rho_H = 2*np.sqrt( u[ind]**2 + v[ind]**2 )
    theta_H = np.arctan2(v[ind], u[ind])
    
    # transform from polar coordinates to cartesian
    di, dj = pol2cart(rho_H, theta_H)
    return di,dj

# no_signals