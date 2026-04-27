"""
Shared utilities for plotting functions.

This module contains common utilities used across different plotting modules,
including axis setup, color management, and legend formatting.
"""

import matplotlib.pyplot as plt
from typing import Optional, Tuple, Any, List, Dict
import matplotlib.axes as mpl_axes
import plotly.colors

# Standard Color Palette for Grid Comparison
COLOR_MAP = {
    "Real": "#2c3e50", # Dark Slate Blue/Grey for Real
    "Real (SWF)": "#2c3e50",
    "Synthetic v1": "#e67e22", # Orange for V1
    "Synthetic v2": "#27ae60", # Green for V2
}
# Fallback colors for Plotly
FALLBACK_COLORS = plotly.colors.qualitative.Plotly

def get_color_map(sources: List[str]) -> Dict[str, str]:
    """
    Dynamically build a color map for Plotly based on present sources.
    
    Parameters
    ----------
    sources : List[str]
        List of source names (e.g. ['Real', 'Synthetic v1']).
        
    Returns
    -------
    Dict[str, str]
        Dictionary mapping source names to hex color codes.
    """
    cmap = {}
    fallback_idx = 0
    for s in sources:
        # Check explicit keys
        if s in COLOR_MAP:
            cmap[s] = COLOR_MAP[s]
            continue
        
        # Check partial matches
        found = False
        for k, v in COLOR_MAP.items():
            if k in s:
                cmap[s] = v
                found = True
                break
        
        if not found:
            cmap[s] = FALLBACK_COLORS[fallback_idx % len(FALLBACK_COLORS)]
            fallback_idx += 1
    return cmap


def setup_axes(
    ax: mpl_axes.Axes,
    xlabel: Optional[str] = None,
    ylabel: Optional[str] = None,
    title: Optional[str] = None,
    grid: bool = True,
    grid_alpha: float = 0.3
) -> mpl_axes.Axes:
    """
    Configure matplotlib axes with common settings.

    Parameters
    ----------
    ax : matplotlib.axes.Axes
        The axes object to configure.
    xlabel : str, optional
        Label for the x-axis.
    ylabel : str, optional
        Label for the y-axis.
    title : str, optional
        Title for the plot.
    grid : bool, optional
        Whether to show grid lines (default: True).
    grid_alpha : float, optional
        Transparency of grid lines (default: 0.3).

    Returns
    -------
    matplotlib.axes.Axes
        The configured axes object.
    """
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=12)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=12)
    if title:
        ax.set_title(title, fontsize=14, fontweight='bold')
    if grid:
        ax.grid(True, alpha=grid_alpha)

    return ax


def create_figure(
    figsize: Tuple[int, int] = (12, 6),
    nrows: int = 1,
    ncols: int = 1,
    **kwargs
) -> Tuple[plt.Figure, Any]:
    """
    Create a matplotlib figure with subplots.

    Parameters
    ----------
    figsize : tuple of int, optional
        Figure size in inches (width, height). Default: (12, 6).
    nrows : int, optional
        Number of subplot rows. Default: 1.
    ncols : int, optional
        Number of subplot columns. Default: 1.
    **kwargs
        Additional keyword arguments passed to plt.subplots().

    Returns
    -------
    tuple
        (Figure, Axes) or (Figure, array of Axes) depending on nrows and ncols.
    """
    fig, axes = plt.subplots(nrows=nrows, ncols=ncols, figsize=figsize, **kwargs)
    return fig, axes


def add_statistics_box(
    ax: mpl_axes.Axes,
    stats_text: str,
    position: str = 'upper right',
    fontsize: int = 10,
    **kwargs
) -> None:
    """
    Add a statistics text box to a plot.

    Parameters
    ----------
    ax : matplotlib.axes.Axes
        The axes object to add the text box to.
    stats_text : str
        The statistics text to display.
    position : str, optional
        Position of the text box. Options: 'upper right', 'upper left',
        'lower right', 'lower left'. Default: 'upper right'.
    fontsize : int, optional
        Font size for the text. Default: 10.
    **kwargs
        Additional keyword arguments for the text box styling.
    """
    position_map = {
        'upper right': (0.98, 0.98, 'top', 'right'),
        'upper left': (0.02, 0.98, 'top', 'left'),
        'lower right': (0.98, 0.02, 'bottom', 'right'),
        'lower left': (0.02, 0.02, 'bottom', 'left')
    }

    x, y, va, ha = position_map.get(position, position_map['upper right'])

    default_bbox = dict(boxstyle='round', facecolor='white', alpha=0.9)
    bbox = kwargs.pop('bbox', default_bbox)

    ax.text(
        x, y, stats_text,
        transform=ax.transAxes,
        verticalalignment=va,
        horizontalalignment=ha,
        bbox=bbox,
        fontsize=fontsize,
        family='monospace',
        **kwargs
    )


def add_limit_lines(
    ax: mpl_axes.Axes,
    limits: dict,
    orientation: str = 'horizontal'
) -> None:
    """
    Add limit lines to a plot (e.g., voltage limits, loading thresholds).

    Parameters
    ----------
    ax : matplotlib.axes.Axes
        The axes object to add limit lines to.
    limits : dict
        Dictionary mapping limit values to their labels and colors.
        Example: {0.95: {'label': 'Min limit', 'color': 'red', 'linestyle': '--'}}
    orientation : str, optional
        Orientation of limit lines: 'horizontal' or 'vertical'. Default: 'horizontal'.
    """
    line_func = ax.axhline if orientation == 'horizontal' else ax.axvline

    for value, properties in limits.items():
        label = properties.get('label', f'Limit: {value}')
        color = properties.get('color', 'red')
        linestyle = properties.get('linestyle', '--')
        linewidth = properties.get('linewidth', 1.5)

        line_func(
            **{('y' if orientation == 'horizontal' else 'x'): value},
            color=color,
            linestyle=linestyle,
            linewidth=linewidth,
            label=label
        )
