import os
import tempfile

import geopandas as gpd
import numpy as np
import pytest
import rioxarray as rioxr

from osgeo import osr

from dhdt.auxilary.handler_rgi import create_rgi_raster, create_rgi_tile_s2


TESTDATA_DIR = 'testdata/RGI'
RGI_SHAPES = f'{TESTDATA_DIR}/shapes.geojson'
EPSG_CODE = 32605
RASTER_SHAPE = (180, 360)


def _set_up_data_for_rgi_raster():
    shapes = gpd.read_file(RGI_SHAPES)
    shapes.set_index('id', inplace=True)

    crs = osr.SpatialReference()
    crs.ImportFromEPSG(EPSG_CODE)

    transform = (461000, 20., 0.,  6624200., 0., -20., *RASTER_SHAPE)
    return shapes, crs, transform


def test_create_rgi_raster_set_up_correct_raster_file():
    shapes, crs, transform = _set_up_data_for_rgi_raster()
    with tempfile.TemporaryDirectory() as tmpdir:
        raster_path = os.path.join(tmpdir, "tmp.tif")
        create_rgi_raster(
            rgi_shapes=shapes,
            geoTransform=transform,
            crs=crs,
            raster_path=raster_path,
        )

        assert os.path.exists(raster_path)
        raster = rioxr.open_rasterio(raster_path)

        assert raster.squeeze().shape == RASTER_SHAPE
        assert raster.rio.crs.to_epsg() == EPSG_CODE

        # Values should include IDs from 1 to 10 and 0 as nodata value
        assert np.all(np.unique(raster) == np.arange(11))


def test_create_rgi_tile_s2_requires_full_mgrs_tile_codes():
    """ Two leading characters needs to be used for the UTM zone """
    with pytest.raises(AssertionError):
        create_rgi_tile_s2(aoi='5VMG')  # should be '05VMG'
