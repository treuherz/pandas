import numpy as np
from numpy.random import randn
import pytest

from pandas import DataFrame, Series, concat
import pandas._testing as tm
from pandas.tests.window.common import (
    moments_consistency_cov_data,
    moments_consistency_is_constant,
    moments_consistency_mock_mean,
    moments_consistency_series_data,
    moments_consistency_std_data,
    moments_consistency_var_data,
    moments_consistency_var_debiasing_factors,
)


@pytest.mark.parametrize("func", ["cov", "corr"])
def test_ewm_pairwise_cov_corr(func, frame):
    result = getattr(frame.ewm(span=10, min_periods=5), func)()
    result = result.loc[(slice(None), 1), 5]
    result.index = result.index.droplevel(1)
    expected = getattr(frame[1].ewm(span=10, min_periods=5), func)(frame[5])
    expected.index = expected.index._with_freq(None)
    tm.assert_series_equal(result, expected, check_names=False)


@pytest.mark.parametrize("name", ["cov", "corr"])
def test_ewm_corr_cov(name, binary_ew_data):
    A, B = binary_ew_data

    result = getattr(A.ewm(com=20, min_periods=5), name)(B)
    assert np.isnan(result.values[:14]).all()
    assert not np.isnan(result.values[14:]).any()


@pytest.mark.parametrize("name", ["cov", "corr"])
def test_ewm_corr_cov_min_periods(name, min_periods, binary_ew_data):
    # GH 7898
    A, B = binary_ew_data
    result = getattr(A.ewm(com=20, min_periods=min_periods), name)(B)
    # binary functions (ewmcov, ewmcorr) with bias=False require at
    # least two values
    assert np.isnan(result.values[:11]).all()
    assert not np.isnan(result.values[11:]).any()

    # check series of length 0
    empty = Series([], dtype=np.float64)
    result = getattr(empty.ewm(com=50, min_periods=min_periods), name)(empty)
    tm.assert_series_equal(result, empty)

    # check series of length 1
    result = getattr(Series([1.0]).ewm(com=50, min_periods=min_periods), name)(
        Series([1.0])
    )
    tm.assert_series_equal(result, Series([np.NaN]))


@pytest.mark.parametrize("name", ["cov", "corr"])
def test_different_input_array_raise_exception(name, binary_ew_data):

    A, _ = binary_ew_data
    msg = "Input arrays must be of the same type!"
    # exception raised is Exception
    with pytest.raises(Exception, match=msg):
        getattr(A.ewm(com=20, min_periods=5), name)(randn(50))


@pytest.mark.slow
@pytest.mark.parametrize("min_periods", [0, 1, 2, 3, 4])
@pytest.mark.parametrize("adjust", [True, False])
@pytest.mark.parametrize("ignore_na", [True, False])
def test_ewm_consistency(consistency_data, min_periods, adjust, ignore_na):
    def _weights(s, com, adjust, ignore_na):
        if isinstance(s, DataFrame):
            if not len(s.columns):
                return DataFrame(index=s.index, columns=s.columns)
            w = concat(
                [
                    _weights(s.iloc[:, i], com=com, adjust=adjust, ignore_na=ignore_na)
                    for i, _ in enumerate(s.columns)
                ],
                axis=1,
            )
            w.index = s.index
            w.columns = s.columns
            return w

        w = Series(np.nan, index=s.index)
        alpha = 1.0 / (1.0 + com)
        if ignore_na:
            w[s.notna()] = _weights(
                s[s.notna()], com=com, adjust=adjust, ignore_na=False
            )
        elif adjust:
            for i in range(len(s)):
                if s.iat[i] == s.iat[i]:
                    w.iat[i] = pow(1.0 / (1.0 - alpha), i)
        else:
            sum_wts = 0.0
            prev_i = -1
            for i in range(len(s)):
                if s.iat[i] == s.iat[i]:
                    if prev_i == -1:
                        w.iat[i] = 1.0
                    else:
                        w.iat[i] = alpha * sum_wts / pow(1.0 - alpha, i - prev_i)
                    sum_wts += w.iat[i]
                    prev_i = i
        return w

    def _variance_debiasing_factors(s, com, adjust, ignore_na):
        weights = _weights(s, com=com, adjust=adjust, ignore_na=ignore_na)
        cum_sum = weights.cumsum().fillna(method="ffill")
        cum_sum_sq = (weights * weights).cumsum().fillna(method="ffill")
        numerator = cum_sum * cum_sum
        denominator = numerator - cum_sum_sq
        denominator[denominator <= 0.0] = np.nan
        return numerator / denominator

    def _ewma(s, com, min_periods, adjust, ignore_na):
        weights = _weights(s, com=com, adjust=adjust, ignore_na=ignore_na)
        result = (
            s.multiply(weights).cumsum().divide(weights.cumsum()).fillna(method="ffill")
        )
        result[
            s.expanding().count() < (max(min_periods, 1) if min_periods else 1)
        ] = np.nan
        return result

    x, is_constant, no_nans = consistency_data
    com = 3.0
    moments_consistency_mock_mean(
        x=x,
        mean=lambda x: x.ewm(
            com=com, min_periods=min_periods, adjust=adjust, ignore_na=ignore_na
        ).mean(),
        mock_mean=lambda x: _ewma(
            x, com=com, min_periods=min_periods, adjust=adjust, ignore_na=ignore_na
        ),
    )

    moments_consistency_is_constant(
        x=x,
        is_constant=is_constant,
        min_periods=min_periods,
        count=lambda x: x.expanding().count(),
        mean=lambda x: x.ewm(
            com=com, min_periods=min_periods, adjust=adjust, ignore_na=ignore_na
        ).mean(),
        corr=lambda x, y: x.ewm(
            com=com, min_periods=min_periods, adjust=adjust, ignore_na=ignore_na
        ).corr(y),
    )

    moments_consistency_var_debiasing_factors(
        x=x,
        var_unbiased=lambda x: (
            x.ewm(
                com=com, min_periods=min_periods, adjust=adjust, ignore_na=ignore_na
            ).var(bias=False)
        ),
        var_biased=lambda x: (
            x.ewm(
                com=com, min_periods=min_periods, adjust=adjust, ignore_na=ignore_na
            ).var(bias=True)
        ),
        var_debiasing_factors=lambda x: (
            _variance_debiasing_factors(x, com=com, adjust=adjust, ignore_na=ignore_na)
        ),
    )


@pytest.mark.parametrize("min_periods", [0, 1, 2, 3, 4])
@pytest.mark.parametrize("adjust", [True, False])
@pytest.mark.parametrize("ignore_na", [True, False])
def test_ewm_consistency_var(consistency_data, min_periods, adjust, ignore_na):
    x, is_constant, no_nans = consistency_data
    com = 3.0
    moments_consistency_var_data(
        x=x,
        is_constant=is_constant,
        min_periods=min_periods,
        count=lambda x: x.expanding().count(),
        mean=lambda x: x.ewm(
            com=com, min_periods=min_periods, adjust=adjust, ignore_na=ignore_na
        ).mean(),
        var_unbiased=lambda x: (
            x.ewm(
                com=com, min_periods=min_periods, adjust=adjust, ignore_na=ignore_na
            ).var(bias=False)
        ),
        var_biased=lambda x: (
            x.ewm(
                com=com, min_periods=min_periods, adjust=adjust, ignore_na=ignore_na
            ).var(bias=True)
        ),
    )


@pytest.mark.parametrize("min_periods", [0, 1, 2, 3, 4])
@pytest.mark.parametrize("adjust", [True, False])
@pytest.mark.parametrize("ignore_na", [True, False])
def test_ewm_consistency_std(consistency_data, min_periods, adjust, ignore_na):
    x, is_constant, no_nans = consistency_data
    com = 3.0
    moments_consistency_std_data(
        x=x,
        var_unbiased=lambda x: (
            x.ewm(
                com=com, min_periods=min_periods, adjust=adjust, ignore_na=ignore_na
            ).var(bias=False)
        ),
        std_unbiased=lambda x: (
            x.ewm(
                com=com, min_periods=min_periods, adjust=adjust, ignore_na=ignore_na
            ).std(bias=False)
        ),
        var_biased=lambda x: (
            x.ewm(
                com=com, min_periods=min_periods, adjust=adjust, ignore_na=ignore_na
            ).var(bias=True)
        ),
        std_biased=lambda x: x.ewm(
            com=com, min_periods=min_periods, adjust=adjust, ignore_na=ignore_na
        ).std(bias=True),
    )


@pytest.mark.parametrize("min_periods", [0, 1, 2, 3, 4])
@pytest.mark.parametrize("adjust", [True, False])
@pytest.mark.parametrize("ignore_na", [True, False])
def test_ewm_consistency_cov(consistency_data, min_periods, adjust, ignore_na):
    x, is_constant, no_nans = consistency_data
    com = 3.0
    moments_consistency_cov_data(
        x=x,
        var_unbiased=lambda x: (
            x.ewm(
                com=com, min_periods=min_periods, adjust=adjust, ignore_na=ignore_na
            ).var(bias=False)
        ),
        cov_unbiased=lambda x, y: (
            x.ewm(
                com=com, min_periods=min_periods, adjust=adjust, ignore_na=ignore_na
            ).cov(y, bias=False)
        ),
        var_biased=lambda x: (
            x.ewm(
                com=com, min_periods=min_periods, adjust=adjust, ignore_na=ignore_na
            ).var(bias=True)
        ),
        cov_biased=lambda x, y: (
            x.ewm(
                com=com, min_periods=min_periods, adjust=adjust, ignore_na=ignore_na
            ).cov(y, bias=True)
        ),
    )


@pytest.mark.slow
@pytest.mark.parametrize("min_periods", [0, 1, 2, 3, 4])
@pytest.mark.parametrize("adjust", [True, False])
@pytest.mark.parametrize("ignore_na", [True, False])
def test_ewm_consistency_series_data(consistency_data, min_periods, adjust, ignore_na):
    x, is_constant, no_nans = consistency_data
    com = 3.0
    moments_consistency_series_data(
        x=x,
        mean=lambda x: x.ewm(
            com=com, min_periods=min_periods, adjust=adjust, ignore_na=ignore_na
        ).mean(),
        corr=lambda x, y: x.ewm(
            com=com, min_periods=min_periods, adjust=adjust, ignore_na=ignore_na
        ).corr(y),
        var_unbiased=lambda x: (
            x.ewm(
                com=com, min_periods=min_periods, adjust=adjust, ignore_na=ignore_na
            ).var(bias=False)
        ),
        std_unbiased=lambda x: (
            x.ewm(
                com=com, min_periods=min_periods, adjust=adjust, ignore_na=ignore_na
            ).std(bias=False)
        ),
        cov_unbiased=lambda x, y: (
            x.ewm(
                com=com, min_periods=min_periods, adjust=adjust, ignore_na=ignore_na
            ).cov(y, bias=False)
        ),
        var_biased=lambda x: (
            x.ewm(
                com=com, min_periods=min_periods, adjust=adjust, ignore_na=ignore_na
            ).var(bias=True)
        ),
        std_biased=lambda x: x.ewm(
            com=com, min_periods=min_periods, adjust=adjust, ignore_na=ignore_na
        ).std(bias=True),
        cov_biased=lambda x, y: (
            x.ewm(
                com=com, min_periods=min_periods, adjust=adjust, ignore_na=ignore_na
            ).cov(y, bias=True)
        ),
    )
