"""Keep Matplotlib's font subset tags and SVG identifiers stable."""

from matplotlib.backends.backend_pdf import PdfFile
from matplotlib import rcParams


def configure_deterministic_pdf() -> None:
    # Matplotlib 3.11 otherwise derives this tag from process-varying font maps.
    PdfFile._get_subset_prefix = staticmethod(lambda _charset: "MPLFIX+")
    rcParams["svg.hashsalt"] = "mirrorplan-paper-figures"
