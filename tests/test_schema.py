from tpga.synthetic_data import make_synthetic_gap_data
from tpga.data_schema import validate_input_frame


def test_schema_ok_for_sample():
    df = make_synthetic_gap_data(n=20)
    report = validate_input_frame(df)
    assert report.ok
    assert report.rows == 20
