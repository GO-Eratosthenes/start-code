import math
import numpy as np

from scipy import ndimage # for image filtering

from skimage import measure
from skimage import segmentation # for superpixels
from skimage import color # for labeling image

from rasterio.features import shapes # for raster to polygon

from shapely.geometry import shape
from shapely.geometry import Point, LineString
from shapely.geos import TopologicalError # for troubleshooting

from ..generic.mapping_tools import castOrientation


# geometric functions
def getShadowPolygon(M, sizPix, thres):  # pre-processing
    """
    Use superpixels to group and label an image
    input:   M              array (m x n)     array with intensity values
             sizPix         integer           window size of the kernel
             thres          integer           threshold value for
                                              Region Adjacency Graph
    output:  labels         array (m x n)     array with numbered labels
             SupPix         array (m x n)     array with numbered superpixels
    """

    mn = np.ceil(np.divide(np.nanprod(M.shape), sizPix));
    SupPix = segmentation.slic(M, sigma=1,
                               n_segments=mn,
                               compactness=0.010)  # create super pixels

    #    g = graph.rag_mean_color(M, SupPix) # create region adjacency graph
    #    mc = np.empty(len(g))
    #    for n in g:
    #        mc[n] = g.nodes[n]['mean color'][1]
    #    graphCut = graph.cut_threshold(SupPix, g, thres)
    #    meanIm = color.label2rgb(graphCut, M, kind='avg')
    meanIm = color.label2rgb(SupPix, M, kind='avg')
    sturge = 1.6 * (math.log2(mn) + 1)
    values, base = np.histogram(np.reshape(meanIm, -1),
                                bins=np.int(np.ceil(sturge)))
    dips = findValley(values, base, 2)
    val = max(dips)
    #    val = filters.threshold_otsu(meanIm)
    #    val = filters.threshold_yen(meanIm)
    imSeparation = meanIm > val
    labels = measure.label(imSeparation, background=0)
    labels = np.int16(
        labels)  # so it can be used for the boundaries extraction
    return labels, SupPix


def medianFilShadows(M, siz, loop):  # pre-processing
    """
    Transform intensity to more clustered intensity, through iterative
    filtering with a median operation
    input:   M              array (m x n)     array with intensity values
             siz            integer           window size of the kernel
             loop           integer           number of iterations
    output:  Mmed           array (m x n)     array wit stark edges
    """
    Mmed = M
    for i in range(loop):
        Mmed = ndimage.median_filter(M, size=siz)
    return Mmed


def sturge(M):  # pre-processing
    """
    Transform intensity to labelled image
    input:   M              array (m x n)     array with intensity values
    output:  labels         array (m x n)     array with numbered labels
    """
    mn = M.size;
    sturge = 1.6 * (math.log2(mn) + 1)
    values, base = np.histogram(np.reshape(M, -1),
                                bins=np.int(np.ceil(sturge)))
    dips = findValley(values, base, 2)
    val = max(dips)
    imSeparation = M > val
    labels = measure.label(imSeparation, background=0)
    return labels


def findValley(values, base, neighbors=2):  # pre-processing
    """
    A valley is a point which has "n" consequative higher values on both sides
    input:   values         array (m x 1)     vector with number of occurances
             base           array (m x 1)     vector with central values
             neighbors      integer           number of neighbors needed
                                              in order to be a valley
    output:  dips           array (n x 1)     array with valley locations
    """
    for i in range(neighbors):
        if i == 0:
            wallP = np.roll(values, +(i + 1))
            wallM = np.roll(values, -(i + 1))
        else:
            wallP = np.vstack((wallP, np.roll(values, +(i + 1))))
            wallM = np.vstack((wallM, np.roll(values, -(i + 1))))
    if neighbors > 1:
        concavP = np.all(np.sign(np.diff(wallP, n=1, axis=0)) == +1, axis=0)
        concavM = np.all(np.sign(np.diff(wallM, n=1, axis=0)) == +1, axis=0)
    selec = np.all(np.vstack((concavP, concavM)), axis=0)
    selec = selec[neighbors - 1:-(neighbors + 1)]
    idx = base[neighbors - 1:-(neighbors + 2)]
    dips = idx[selec]
    # walls = np.amin(sandwich,axis=0)
    # selec = values<walls
    return dips


def labelOccluderAndCasted(labeling, sunAz):  # pre-processing
    """
    Find along the edge, the casting and casted pixels of a polygon
    input:   labeling       array (n x m)     array with labelled polygons
             sunAz          array (n x m)     band of azimuth values
    output:  shadowIdx      array (m x m)     array with numbered pairs, where
                                              the caster is the positive number
                                              the casted is the negative number
    """
    labeling = labeling.astype(np.int64)
    msk = labeling >= 1
    mL, nL = labeling.shape
    shadowIdx = np.zeros((mL, nL), dtype=np.int16)
    # shadowRid = np.zeros((mL,nL), dtype=np.int16)
    inner = ndimage.morphology.binary_erosion(msk)
    # inner = ndimage.morphology.binary_dilation(msk==0)&msk
    bndOrient = castOrientation(inner.astype(np.float), sunAz)
    del mL, nL, inner

    # labelList = np.unique(labels[msk])
    # locs = ndimage.find_objects(labeling, max_label=0)

    labList = np.unique(labeling)
    labList = labList[labList != 0]
    for i in labList:
        selec = labeling == i
        labIdx = np.nonzero(selec)
        labImin = np.min(labIdx[0])
        labImax = np.max(labIdx[0])
        labJmin = np.min(labIdx[1])
        labJmax = np.max(labIdx[1])
        subMsk = selec[labImin:labImax, labJmin:labJmax]

        #    for i,loc in enumerate(locs):
        #        subLabel = labels[loc]

        #    for i in range(len(locs)): # range(1,labels.max()): # loop through all polygons
        #        # print("Starting on number %s" % (i))
        #        loc = locs[i]
        #        if loc is not None:
        #            subLabel = labels[loc] # generate subset covering only the polygon
        # slices seem to be coupled.....
        #            subLabel = labels[loc[0].start:loc[0].stop,loc[1].start:loc[1].stop]
        #        subLabel[subLabel!=(i+0)] = 0   # de boosdoener
        subOrient = np.sign(bndOrient[labImin:labImax,
                            labJmin:labJmax])  # subOrient = np.sign(bndOrient[loc])

        # subMsk = subLabel==(i+0)
        # subBound = subMsk & ndimage.morphology.binary_dilation(subMsk==0)
        subBound = subMsk ^ ndimage.morphology.binary_erosion(subMsk)
        subOrient[~subBound] = 0  # remove other boundaries

        subAz = sunAz[labImin:labImax,
                labJmin:labJmax]  # [loc] # subAz = sunAz[loc]

        subWhe = np.nonzero(subMsk)
        ridgIdx = subOrient[subWhe[0], subWhe[1]] == 1
        try:
            ridgeI = subWhe[0][ridgIdx]
            ridgeJ = subWhe[1][ridgIdx]
        except IndexError:
            continue
            # try:
        #     shadowRid[labIdx] = i # shadowRid[loc] = i # shadowRid[ridgeI+(loc[0].start),ridgeJ+(loc[1].start)] = i
        # except IndexError:
        #     print('iets aan de hand')

        cast = subOrient == -1  # boundary of the polygon that receives cast shadow

        m, n = subMsk.shape
        print("For number %s : Size is %s by %s finding %s pixels" % (
        i, m, n, len(ridgeI)))

        for x in range(len(ridgeI)):  # loop through all occluders
            sunDir = subAz[ridgeI[x]][ridgeJ[x]]  # degrees [-180 180]

            # Bresenham's line algorithm
            dI = -math.cos(math.radians(subAz[ridgeI[x]][ridgeJ[
                x]]))  # -cos # flip axis to get from world into image coords
            dJ = -math.sin(math.radians(subAz[ridgeI[x]][ridgeJ[x]]))  # -sin #
            if abs(sunDir) > 90:  # northern hemisphere
                if dI > dJ:
                    rr = np.arange(start=0, stop=ridgeI[x], step=1)
                    cc = np.flip(np.round(rr * dJ), axis=0) + ridgeJ[x]
                else:
                    cc = np.arange(start=0, stop=ridgeJ[x], step=1)
                    rr = np.flip(np.round(cc * dI), axis=0) + ridgeI[x]
            else:  # southern hemisphere
                if dI > dJ:
                    rr = np.arange(start=ridgeI[x], stop=m, step=1)
                    cc = np.round(rr * dJ) + ridgeJ[x]
                else:
                    cc = np.arange(start=ridgeJ[x], stop=n, step=1)
                    rr = np.round(cc * dI) + ridgeI[x]
                    # generate cast line in sub-image
            rr = rr.astype(np.int64)
            cc = cc.astype(np.int64)
            subCast = np.zeros((m, n), dtype=np.uint8)

            IN = (cc >= 0) & (cc <= n) & (rr >= 0) & (
                        rr <= m)  # inside sub-image
            if IN.any():
                rr = rr[IN]
                cc = cc[IN]
                try:
                    subCast[rr, cc] = 1
                except IndexError:
                    continue

                    # find closest casted
                castHit = cast & subCast
                castIdx = castHit[subWhe[0], subWhe[1]] == True
                castI = subWhe[0][castIdx]
                castJ = subWhe[1][castIdx]
                del IN, castIdx, castHit, subCast, rr, cc, dI, dJ, sunDir

                if len(castI) > 1:
                    # do selection of the closest casted
                    dist = np.sqrt(
                        (castI - ridgeI[x]) ** 2 + (castJ - ridgeJ[x]) ** 2)
                    idx = np.where(dist == np.amin(dist))
                    castI = castI[idx[0]]
                    castJ = castJ[idx[0]]

                if len(castI) > 0:
                    # write out
                    shadowIdx[ridgeI[x] + labImin][ridgeJ[x] + labJmin] = +x
                    # shadowIdx[ridgeI[x]+loc[0].start][ridgeJ[x]+loc[1].start] = +x # ridge
                    shadowIdx[castI[0] + labImin][castJ[0] + labJmin] = -x
                    # shadowIdx[castI[0]+loc[0].start][castJ[0]+loc[1].start] = -x # casted
            #     else:
            #         print('out of bounds')
            # else:
            #     print('out of bounds')

            subShadowIdx = shadowIdx[labImin:labImax,
                           labJmin:labJmax]  # subShadowIdx = shadowIdx[loc]
            # subShadowOld = shadowIdx[loc] # make sur other are not overwritten
            # OLD = subShadowOld!=0
            # subShadowIdx[OLD] = subShadowOld[OLD]
            # shadowIdx[loc] = subShadowIdx
    return shadowIdx  # , shadowRid


def listOccluderAndCasted(labels, sunZn, sunAz,
                          geoTransform):  # pre-processing
    """
    Find along the edge, the casting and casted pixels of a polygon
    input:   labels         array (n x m)     array with labelled polygons
             sunAz          array (n x m)     band of azimuth values
             sunZn          array (n x m)     band of zentih values
    output:  castList       list  (k x 6)     array with image coordinates of
                                              caster and casted with the
                                              sun angles of the caster
    """
    msk = labels > 1
    labels = labels.astype(np.int32)
    mskOrient = castOrientation(msk.astype(np.float), sunAz)
    mskOrient = np.sign(mskOrient)
    # makeGeoIm(mskOrient,subTransform,crs,"polyRidges.tif")

    castList = []
    for shp, val in shapes(labels, mask=msk, connectivity=8):
        #        coord = shp["coordinates"]
        #        coord = np.uint16(np.squeeze(np.array(coord[:])))
        if val != 0:
            #    if val==48:
            # get ridge coordinates
            polygoon = shape(shp)
            polyRast = labels == val  # select the polygon
            polyInnr = ndimage.binary_erosion(polyRast,
                                              np.ones((3, 3),
                                                      dtype=bool))
            polyBoun = np.logical_xor(polyRast, polyInnr)
            polyWhe = np.nonzero(polyBoun)
            ridgIdx = mskOrient[polyWhe[0], polyWhe[1]] == 1
            ridgeI = polyWhe[0][ridgIdx]
            ridgeJ = polyWhe[1][ridgIdx]
            del polyRast, polyInnr, polyBoun, polyWhe, ridgIdx

            for x in range(len(ridgeI)):  # ridgeI:
                try:
                    castLine = LineString([[ridgeJ[x], ridgeI[x]],
                                           [ridgeJ[x]
                                            - (math.sin(math.radians(
                                               sunAz[ridgeI[x]][
                                                   ridgeJ[x]])) * 1e4),
                                            ridgeI[x]
                                            + (math.cos(math.radians(
                                                sunAz[ridgeI[x]][
                                                    ridgeJ[x]])) * 1e4)]])
                except IndexError:
                    continue
                try:
                    castEnd = polygoon.intersection(castLine)
                except TopologicalError:
                    # somehow the exterior of the polygon crosses or touches itself, making it a LinearRing
                    polygoon = polygoon.buffer(0)
                    castEnd = polygoon.intersection(castLine)

                if castEnd.geom_type == 'LineString':
                    castEnd = castEnd.coords[:]
                elif castEnd.geom_type == 'MultiLineString':
                    # castEnd = [list(x.coords) for x in list(castEnd)]
                    cEnd = []
                    for m in list(castEnd):
                        cEnd += m.coords[:]
                    castEnd = cEnd
                    del m, cEnd
                elif castEnd.geom_type == 'GeometryCollection':
                    cEnd = []
                    for m in range(len(castEnd)):
                        cEnd += castEnd[m].coords[:]
                    castEnd = cEnd
                    del m, cEnd
                elif castEnd.geom_type == 'Point':
                    castEnd = []
                else:
                    print('something went wrong?')

                # if empty
                if len(castEnd) > 1:
                    # if len(castEnd.coords[:])>1:
                    # find closest intersection
                    occluder = Point(ridgeJ[x], ridgeI[x])
                    # dists = [Point(c).distance(occluder) for c in castEnd.coords]
                    dists = [Point(c).distance(occluder) for c in castEnd]
                    dists = [float('Inf') if i == 0 else i for i in dists]
                    castIdx = dists.index(min(dists))
                    casted = castEnd[castIdx]

                    # transform to UTM and append to array
                    ridgeX = (ridgeI[x] * geoTransform[2]
                              + ridgeJ[x] * geoTransform[1]
                              + geoTransform[0]
                              )
                    ridgeY = (ridgeI[x] * geoTransform[5]
                              + ridgeJ[x] * geoTransform[4]
                              + geoTransform[3]
                              )
                    castX = (casted[1] * geoTransform[2]
                             + casted[0] * geoTransform[1]
                             + geoTransform[0]
                             )
                    castY = (casted[1] * geoTransform[5]
                             + casted[0] * geoTransform[4]
                             + geoTransform[3]
                             )

                    castLine = np.array([ridgeX, ridgeY, castX, castY,
                                         sunAz[ridgeI[x]][ridgeJ[x]],
                                         sunZn[ridgeI[x]][ridgeJ[x]]])
                    castList.append(castLine)
                    del dists, occluder, castIdx, casted
                del castLine, castEnd
    return castList