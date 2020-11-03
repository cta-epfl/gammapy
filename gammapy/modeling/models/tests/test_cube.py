# Licensed under a 3-clause BSD style license - see LICENSE.rst
import pytest
import numpy as np
from numpy.testing import assert_allclose
import astropy.units as u
from astropy.time import Time
from gammapy.data.gti import GTI
from gammapy.datasets.map import MapEvaluator
from gammapy.irf import EDispKernel, PSFKernel
from gammapy.maps import Map, MapAxis, WcsGeom
from gammapy.modeling.models import (
    SpatialModel,
    BackgroundModel,
    ConstantSpectralModel,
    ConstantTemporalModel,
    GaussianSpatialModel,
    Models,
    PointSpatialModel,
    PowerLawSpectralModel,
    PowerLawNormSpectralModel,
    TemplateSpatialModel,
    CompoundSpectralModel,
    SkyModel,
    create_fermi_isotropic_diffuse_model,
)
from gammapy.utils.testing import requires_data, mpl_plot_check, requires_dependency
from gammapy.modeling import Parameter
from astropy.coordinates.angle_utilities import angular_separation


@pytest.fixture(scope="session")
def sky_model():
    spatial_model = GaussianSpatialModel(
        lon_0="3 deg", lat_0="4 deg", sigma="3 deg", frame="galactic"
    )
    spectral_model = PowerLawSpectralModel(
        index=2, amplitude="1e-11 cm-2 s-1 TeV-1", reference="1 TeV"
    )
    temporal_model = ConstantTemporalModel()
    return SkyModel(
        spatial_model=spatial_model,
        spectral_model=spectral_model,
        temporal_model=temporal_model,
        name="source-1",
    )


@pytest.fixture(scope="session")
def gti():
    start = [1, 3, 5] * u.day
    stop = [2, 3.5, 6] * u.day
    t_ref = Time(55555, format="mjd")
    gti = GTI.create(start, stop, reference_time=t_ref)
    return gti


@pytest.fixture(scope="session")
def diffuse_model():
    axis = MapAxis.from_nodes([0.1, 100], name="energy_true", unit="TeV", interp="log")
    m = Map.create(
        npix=(4, 3), binsz=2, axes=[axis], unit="cm-2 s-1 MeV-1 sr-1", frame="galactic"
    )
    m.data += 42
    spatial_model = TemplateSpatialModel(m, normalize=False)
    return SkyModel(PowerLawNormSpectralModel(), spatial_model)


@pytest.fixture(scope="session")
def geom():
    axis = MapAxis.from_edges(np.logspace(-1, 1, 3), unit=u.TeV, name="energy")
    return WcsGeom.create(skydir=(0, 0), npix=(5, 4), frame="galactic", axes=[axis])


@pytest.fixture(scope="session")
def geom_true():
    axis = MapAxis.from_edges(np.logspace(-1, 1, 4), unit=u.TeV, name="energy_true")
    return WcsGeom.create(skydir=(0, 0), npix=(5, 4), frame="galactic", axes=[axis])


@pytest.fixture(scope="session")
def exposure(geom_true):
    m = Map.from_geom(geom_true)
    m.quantity = np.ones(geom_true.data_shape) * u.Quantity("100 m2 s")
    m.data[1] *= 10
    return m


@pytest.fixture(scope="session")
def background(geom):
    m = Map.from_geom(geom)
    m.quantity = np.ones(geom.data_shape) * 1e-7
    return m


@pytest.fixture(scope="session")
def edisp(geom, geom_true):
    e_reco = geom.axes["energy"].edges
    e_true = geom_true.axes["energy_true"].edges
    return EDispKernel.from_diagonal_response(
        energy_true=e_true, energy=e_reco
    )


@pytest.fixture(scope="session")
def psf(geom_true):
    sigma = 0.5 * u.deg
    return PSFKernel.from_gauss(geom_true, sigma)


@pytest.fixture(scope="session")
def evaluator(sky_model, exposure, psf, edisp, gti):
    return MapEvaluator(sky_model, exposure, psf=psf, edisp=edisp, gti=gti)


@pytest.fixture(scope="session")
def diffuse_evaluator(diffuse_model, exposure, psf, edisp):
    return MapEvaluator(diffuse_model, exposure, psf=psf, edisp=edisp)


@pytest.fixture(scope="session")
def sky_models(sky_model):
    sky_model_2 = sky_model.copy(name="source-2")
    sky_model_3 = sky_model.copy(name="source-3")
    return Models([sky_model_2, sky_model_3])


@pytest.fixture(scope="session")
def sky_models_2(sky_model):
    sky_model_4 = sky_model.copy(name="source-4")
    sky_model_5 = sky_model.copy(name="source-5")
    return Models([sky_model_4, sky_model_5])


def test_sky_model_init():
    with pytest.raises(TypeError):
        spatial_model = GaussianSpatialModel()
        SkyModel(spectral_model=1234, spatial_model=spatial_model)

    with pytest.raises(TypeError):
        SkyModel(spectral_model=PowerLawSpectralModel(), spatial_model=1234)


def test_sky_model_spatial_none_io(tmpdir):
    pwl = PowerLawSpectralModel()
    model = SkyModel(spectral_model=pwl, name="test")
    models = Models([model])

    filename = tmpdir / "test-models-none.yaml"
    models.write(filename)

    models = Models.read(filename)

    assert models["test"].spatial_model is None


def test_sky_model_spatial_none_evaluate(geom_true, gti):
    pwl = PowerLawSpectralModel()
    model = SkyModel(spectral_model=pwl, name="test")

    data = model.evaluate_geom(geom_true, gti).to_value("cm-2 s-1 TeV-1")

    assert data.shape == (3, 1, 1)
    assert_allclose(data[0], 1.256774e-11, rtol=1e-6)


def test_skymodel_addition(sky_model, sky_models, sky_models_2, diffuse_model):
    models = sky_model + sky_model.copy()
    assert isinstance(models, Models)
    assert len(models) == 2

    models = sky_model + sky_models
    assert isinstance(models, Models)
    assert len(models) == 3

    models = sky_models + sky_model
    assert isinstance(models, Models)
    assert len(models) == 3

    models = sky_models + diffuse_model
    assert isinstance(models, Models)
    assert len(models) == 3

    models = sky_models + sky_models_2
    assert isinstance(models, Models)
    assert len(models) == 4

    models = sky_model + sky_models
    assert isinstance(models, Models)
    assert len(models) == 3


def test_background_model(background):
    bkg1 = BackgroundModel(background)
    bkg1.spectral_model.norm.value = 2.0
    npred1 = bkg1.evaluate()
    assert_allclose(npred1.data[0][0][0], background.data[0][0][0] * 2.0, rtol=1e-3)
    assert_allclose(npred1.data.sum(), background.data.sum() * 2.0, rtol=1e-3)

    bkg2 = BackgroundModel(background)
    bkg2.spectral_model.norm.value = 2.0
    bkg2.spectral_model.tilt.value = 0.2
    bkg2.spectral_model.reference.quantity = "1000 GeV"

    npred2 = bkg2.evaluate()
    assert_allclose(npred2.data[0][0][0], 2.254e-07, rtol=1e-3)
    assert_allclose(npred2.data.sum(), 7.352e-06, rtol=1e-3)


def test_background_model_io(tmpdir, background):
    filename = str(tmpdir / "test-bkg-file.fits")
    bkg = BackgroundModel(background, filename=filename)
    bkg.spectral_model.norm.value = 2.0
    bkg.map.write(filename, overwrite=True)
    bkg_dict = bkg.to_dict()
    bkg_read = bkg.from_dict(bkg_dict)

    assert_allclose(
        bkg_read.evaluate().data.sum(), background.data.sum() * 2.0, rtol=1e-3
    )
    assert bkg_read.filename == filename


class TestSkyModels:
    @staticmethod
    def test_parameters(sky_models):
        parnames = [
            "index",
            "amplitude",
            "reference",
            "lon_0",
            "lat_0",
            "sigma",
            "e",
            "phi",
        ] * 2
        assert sky_models.parameters.names == parnames

        # Check that model parameters are references to the parts
        p1 = sky_models.parameters["lon_0"]
        p2 = sky_models[0].parameters["lon_0"]
        assert p1 is p2

    @staticmethod
    def test_str(sky_models):
        assert "Component 0" in str(sky_models)
        assert "Component 1" in str(sky_models)

    @staticmethod
    def test_get_item(sky_models):
        model = sky_models["source-2"]
        assert model.name == "source-2"

        model = sky_models["source-3"]
        assert model.name == "source-3"

        with pytest.raises(ValueError):
            sky_models["spam"]

    @staticmethod
    def test_names(sky_models):
        assert sky_models.names == ["source-2", "source-3"]


@requires_data()
def test_models_mutation(sky_model, sky_models, sky_models_2):
    mods = sky_models

    mods.insert(0, sky_model)
    assert mods.names == ["source-1", "source-2", "source-3"]

    mods.extend(sky_models_2)
    assert mods.names == ["source-1", "source-2", "source-3", "source-4", "source-5"]

    mod3 = mods[3]
    mods.remove(mods[3])
    assert mods.names == ["source-1", "source-2", "source-3", "source-5"]
    mods.append(mod3)
    assert mods.names == ["source-1", "source-2", "source-3", "source-5", "source-4"]
    mods.pop(3)
    assert mods.names == ["source-1", "source-2", "source-3", "source-4"]

    with pytest.raises(ValueError, match="Model names must be unique"):
        mods.append(sky_model)
    with pytest.raises(ValueError, match="Model names must be unique"):
        mods.insert(0, sky_model)
    with pytest.raises(ValueError, match="Model names must be unique"):
        mods.extend(sky_models_2)
    with pytest.raises(ValueError, match="Model names must be unique"):
        mods = sky_models + sky_models_2


class TestSkyModel:
    @staticmethod
    def test_repr(sky_model):
        assert "SkyModel" in repr(sky_model)

    @staticmethod
    def test_str(sky_model):
        assert "SkyModel" in str(sky_model)

    @staticmethod
    def test_parameters(sky_model):
        # Check that model parameters are references to the spatial and spectral parts
        p1 = sky_model.parameters["lon_0"]
        p2 = sky_model.spatial_model.parameters["lon_0"]
        assert p1 is p2

        p1 = sky_model.parameters["amplitude"]
        p2 = sky_model.spectral_model.parameters["amplitude"]
        assert p1 is p2

    @staticmethod
    def test_evaluate_scalar(sky_model):
        lon = 3 * u.deg
        lat = 4 * u.deg
        energy = 1 * u.TeV

        q = sky_model.evaluate(lon, lat, energy)

        assert q.unit == "cm-2 s-1 TeV-1 sr-1"
        assert np.isscalar(q.value)
        assert_allclose(q.to_value("cm-2 s-1 TeV-1 deg-2"), 1.76879232e-13)

    @staticmethod
    def test_evaluate_array(sky_model):
        lon = 3 * u.deg * np.ones(shape=(3, 4))
        lat = 4 * u.deg * np.ones(shape=(3, 4))
        energy = [1, 1, 1, 1, 1] * u.TeV

        q = sky_model.evaluate(lon, lat, energy[:, np.newaxis, np.newaxis])

        assert q.shape == (5, 3, 4)
        assert_allclose(q.to_value("cm-2 s-1 TeV-1 deg-2"), 1.76879232e-13)

    @staticmethod
    def test_processing(sky_model):
        assert sky_model.apply_irf == {"exposure": True, "psf": True, "edisp": True}
        out = sky_model.to_dict()
        assert "apply_irf" not in out

        sky_model.apply_irf["edisp"] = False
        out = sky_model.to_dict()
        assert out["apply_irf"] == {"exposure": True, "psf": True, "edisp": False}
        sky_model.apply_irf["edisp"] = True


class Test_Template_with_cube:
    @staticmethod
    def test_evaluate_scalar(diffuse_model):
        # Check pixel inside map
        val = diffuse_model.evaluate(0 * u.deg, 0 * u.deg, 10 * u.TeV)
        assert val.unit == "cm-2 s-1 MeV-1 sr-1"
        assert val.shape == (1,)
        assert_allclose(val.value, 42)

        # Check pixel outside map (spatially)
        val = diffuse_model.evaluate(100 * u.deg, 0 * u.deg, 10 * u.TeV)
        assert_allclose(val.value, 0)

        # Check pixel outside energy range
        val = diffuse_model.evaluate(0 * u.deg, 0 * u.deg, 200 * u.TeV)
        assert_allclose(val.value, 0)

    @staticmethod
    def test_evaluate_array(diffuse_model):
        lon = 1 * u.deg * np.ones(shape=(3, 4))
        lat = 2 * u.deg * np.ones(shape=(3, 4))
        energy = [1, 1, 1, 1, 1] * u.TeV

        q = diffuse_model.evaluate(lon, lat, energy[:, np.newaxis, np.newaxis])

        assert q.shape == (5, 3, 4)
        assert_allclose(q.value.mean(), 42)

    @staticmethod
    @requires_data()
    def test_read():
        model = TemplateSpatialModel.read(
            "$GAMMAPY_DATA/tests/unbundled/fermi/gll_iem_v02_cutout.fits",
            normalize=False,
        )
        assert model.map.unit == "cm-2 s-1 MeV-1 sr-1"

        # Check pixel inside map
        val = model.evaluate(0 * u.deg, 0 * u.deg, 100 * u.GeV)
        assert val.unit == "cm-2 s-1 MeV-1 sr-1"
        assert val.shape == (1,)
        assert_allclose(val.value, 1.396424e-12, rtol=1e-5)

    @staticmethod
    def test_evaluation_radius(diffuse_model):
        radius = diffuse_model.evaluation_radius
        assert radius.unit == "deg"
        assert_allclose(radius.value, 4)

    @staticmethod
    def test_frame(diffuse_model):
        assert diffuse_model.frame == "galactic"

    @staticmethod
    def test_processing(diffuse_model):
        assert diffuse_model.apply_irf == {"exposure": True, "psf": True, "edisp": True}
        out = diffuse_model.to_dict()
        assert "apply_irf" not in out

        diffuse_model.apply_irf["edisp"] = False
        out = diffuse_model.to_dict()
        assert out["apply_irf"] == {"exposure": True, "psf": True, "edisp": False}
        diffuse_model.apply_irf["edisp"] = True

    @staticmethod
    def test_datasets_name(diffuse_model):
        assert diffuse_model.datasets_names is None

        diffuse_model.datasets_names = ["1", "2"]
        out = diffuse_model.to_dict()
        assert out["datasets_names"] == ["1", "2"]

        diffuse_model.datasets_names = None
        out = diffuse_model.to_dict()
        assert "datasets_names" not in out


class Test_template_cube_MapEvaluator:
    @staticmethod
    def test_compute_dnde(diffuse_evaluator):
        out = diffuse_evaluator.compute_dnde()
        assert out.shape == (3, 4, 5)
        out = out.to("cm-2 s-1 MeV-1 sr-1")
        assert_allclose(out.value.sum(), 2520.0, rtol=1e-5)
        assert_allclose(out.value[0, 0, 0], 42, rtol=1e-5)

    @staticmethod
    def test_compute_flux(diffuse_evaluator):
        out = diffuse_evaluator.compute_flux()
        assert out.data.shape == (3, 4, 5)
        out = out.quantity.to("cm-2 s-1")
        assert_allclose(out.value.sum(), 633263.444803, rtol=1e-5)
        assert_allclose(out.value[0, 0, 0], 1164.656176, rtol=1e-5)

    @staticmethod
    def test_apply_psf(diffuse_evaluator):
        flux = diffuse_evaluator.compute_flux()
        npred = diffuse_evaluator.apply_exposure(flux)
        out = diffuse_evaluator.apply_psf(npred)
        assert out.data.shape == (3, 4, 5)
        assert_allclose(out.data.sum(), 1.106404e12, rtol=1e-5)
        assert_allclose(out.data[0, 0, 0], 5.586508e08, rtol=1e-5)

    @staticmethod
    def test_apply_edisp(diffuse_evaluator):
        flux = diffuse_evaluator.compute_flux()
        npred = diffuse_evaluator.apply_exposure(flux)
        out = diffuse_evaluator.apply_edisp(npred)
        assert out.data.shape == (2, 4, 5)
        assert_allclose(out.data.sum(), 1.606345e12, rtol=1e-5)
        assert_allclose(out.data[0, 0, 0], 1.83018e+10, rtol=1e-5)

    @staticmethod
    def test_compute_npred(diffuse_evaluator):
        out = diffuse_evaluator.compute_npred()
        assert out.data.shape == (2, 4, 5)
        assert_allclose(out.data.sum(), 1.106403e12, rtol=1e-5)
        assert_allclose(out.data[0, 0, 0], 8.778828e+09, rtol=1e-5)


class TestSkyModelMapEvaluator:
    @staticmethod
    def test_compute_dnde(evaluator):
        out = evaluator.compute_dnde()
        assert out.shape == (3, 4, 5)
        assert out.unit == "cm-2 s-1 TeV-1 sr-1"
        assert_allclose(
            out.to_value("cm-2 s-1 TeV-1 deg-2").sum(),
            1.1788166328203174e-11,
            rtol=1e-5,
        )
        assert_allclose(
            out.to_value("cm-2 s-1 TeV-1 deg-2")[0, 0, 0],
            5.087056282039508e-13,
            rtol=1e-5,
        )

    @staticmethod
    def test_compute_flux(evaluator):
        out = evaluator.compute_flux()
        out = out.quantity.to_value("cm-2 s-1")
        assert out.shape == (3, 4, 5)
        assert_allclose(out.sum(), 2.213817e-12, rtol=1e-5)
        assert_allclose(out[0, 0, 0], 7.938388e-14, rtol=1e-5)

    @staticmethod
    def test_apply_psf(evaluator):
        flux = evaluator.compute_flux()
        npred = evaluator.apply_exposure(flux)
        out = evaluator.apply_psf(npred)
        assert out.data.shape == (3, 4, 5)
        assert_allclose(out.data.sum(), 3.862314e-06, rtol=1e-5)
        assert_allclose(out.data[0, 0, 0], 4.126612e-08, rtol=1e-5)

    @staticmethod
    def test_apply_edisp(evaluator):
        flux = evaluator.compute_flux()
        npred = evaluator.apply_exposure(flux)
        out = evaluator.apply_edisp(npred)
        assert out.data.shape == (2, 4, 5)
        assert_allclose(out.data.sum(), 5.615601e-06, rtol=1e-5)
        assert_allclose(out.data[0, 0, 0], 1.33602e-07, rtol=1e-5)

    @staticmethod
    def test_compute_npred(evaluator, gti):
        out = evaluator.compute_npred()
        assert out.data.shape == (2, 4, 5)
        assert_allclose(out.data.sum(), 3.862314e-06, rtol=1e-5)
        assert_allclose(out.data[0, 0, 0], 6.94503e-08, rtol=1e-5)


def test_sky_point_source():
    # Test special case of point source. Regression test for GH 2367.

    energy_axis = MapAxis.from_edges(
        [1, 10], unit="TeV", name="energy_true", interp="log"
    )
    exposure = Map.create(
        skydir=(100, 70),
        npix=(4, 4),
        binsz=0.1,
        proj="AIT",
        unit="cm2 s",
        axes=[energy_axis],
    )
    exposure.data = np.ones_like(exposure.data)

    spatial_model = PointSpatialModel(
        lon_0=100.06 * u.deg, lat_0=70.03 * u.deg, frame="icrs"
    )
    # Create a spectral model with integral flux of 1 cm-2 s-1 in this energy band
    spectral_model = ConstantSpectralModel(const="1 cm-2 s-1 TeV-1")
    spectral_model.const.value /= spectral_model.integral(1 * u.TeV, 10 * u.TeV).value
    model = SkyModel(spatial_model=spatial_model, spectral_model=spectral_model)
    evaluator = MapEvaluator(model=model, exposure=exposure)
    flux = evaluator.compute_flux().quantity.to_value("cm-2 s-1")[0]

    expected = [
        [0, 0, 0, 0],
        [0, 0.140, 0.058, 0.0],
        [0, 0.564, 0.236, 0],
        [0, 0, 0, 0],
    ]
    assert_allclose(flux, expected, atol=0.01)

    assert_allclose(flux.sum(), 1)


@requires_data()
def test_fermi_isotropic():
    filename = "$GAMMAPY_DATA/fermi_3fhl/iso_P8R2_SOURCE_V6_v06.txt"
    model = create_fermi_isotropic_diffuse_model(filename)
    coords = {"lon": 0 * u.deg, "lat": 0 * u.deg, "energy": 50 * u.GeV}

    flux = model(**coords)

    assert_allclose(flux.value, 1.463e-13, rtol=1e-3)
    assert flux.unit == "MeV-1 cm-2 s-1 sr-1"
    assert isinstance(model.spectral_model, CompoundSpectralModel)


class MyCustomGaussianModel(SpatialModel):
    """My custom gaussian model.

    Parameters
    ----------
    lon_0, lat_0 : `~astropy.coordinates.Angle`
        Center position
    sigma_1TeV : `~astropy.coordinates.Angle`
        Width of the Gaussian at 1 TeV
    sigma_10TeV : `~astropy.coordinates.Angle`
        Width of the Gaussian at 10 TeV

    """

    tag = "MyCustomGaussianModel"
    lon_0 = Parameter("lon_0", "0 deg")
    lat_0 = Parameter("lat_0", "0 deg", min=-90, max=90)

    sigma_1TeV = Parameter("sigma_1TeV", "1 deg", min=0)
    sigma_10TeV = Parameter("sigma_10TeV", "0.5 deg", min=0)

    @staticmethod
    def evaluate(lon, lat, energy, lon_0, lat_0, sigma_1TeV, sigma_10TeV):
        """Evaluate custom Gaussian model"""
        sigmas = u.Quantity([sigma_1TeV, sigma_10TeV])
        energy_nodes = [1, 10] * u.TeV
        sigma = np.interp(energy, energy_nodes, sigmas)

        sep = angular_separation(lon, lat, lon_0, lat_0)

        exponent = -0.5 * (sep / sigma) ** 2
        norm = 1 / (2 * np.pi * sigma ** 2)
        return norm * np.exp(exponent)

    @property
    def evaluation_radius(self):
        """Evaluation radius (`~astropy.coordinates.Angle`)."""
        return 5 * self.sigma_1TeV.quantity


def test_energy_dependent_model(geom_true):
    spectral_model = PowerLawSpectralModel(amplitude="1e-11 cm-2 s-1 TeV-1")
    spatial_model = MyCustomGaussianModel(frame="galactic")
    sky_model = SkyModel(spectral_model=spectral_model, spatial_model=spatial_model)
    model = sky_model.integrate_geom(geom_true)

    assert_allclose(model.data.sum(), 1.678314e-14, rtol=1e-3)


@requires_dependency("matplotlib")
def test_plot_grid(geom_true):
    spatial_model = MyCustomGaussianModel(frame="galactic")
    with mpl_plot_check():
        spatial_model.plot_grid(geom=geom_true)


def test_sky_model_create():
    m = SkyModel.create("pl", "point", name="my-source")
    assert isinstance(m.spatial_model, PointSpatialModel)
    assert isinstance(m.spectral_model, PowerLawSpectralModel)
    assert m.name == "my-source"
