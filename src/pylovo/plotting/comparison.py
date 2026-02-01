import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from typing import Optional, List, Dict

# Standard Color Palette
COLOR_MAP = {
    "Real": "#2c3e50", # Dark Slate Blue/Grey for Real
    "Real (SWF)": "#2c3e50",
    "Synthetic v1": "#e67e22", # Orange for V1
    "Synthetic v2": "#27ae60", # Green for V2
}
# Fallback colors
FALLBACK_COLORS = px.colors.qualitative.Plotly

def get_color_map(sources: List[str]) -> Dict[str, str]:
    """Dynamically build color map based on present sources."""
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

def plot_metric_distribution(
    df: pd.DataFrame, 
    metric_col: str, 
    title: Optional[str] = None,
    hover_data: Optional[List[str]] = None,
    plot_type: str = "box"
) -> go.Figure:
    """
    Generate a distribution plot (Box, Violin, or Strip) for a given metric.
    """
    if df.empty:
        return go.Figure().add_annotation(text="No Data Available", showarrow=False)

    if hover_data is None:
        hover_data = ["grid_result_id", "kcid", "bcid"]
        # Filter columns
        hover_data = [c for c in hover_data if c in df.columns]

    sources = df["source"].unique()
    color_discrete_map = get_color_map(sources)

    common_args = {
        "data_frame": df,
        "x": "source",
        "y": metric_col,
        "color": "source",
        "color_discrete_map": color_discrete_map,
        "hover_data": hover_data,
        "title": title or f"Distribution of {metric_col}",
        "template": "plotly_white"
    }

    if plot_type == "box":
        fig = px.box(**common_args, points="all")
    elif plot_type == "violin":
        fig = px.violin(**common_args, box=True, points="all")
    elif plot_type == "strip":
        fig = px.strip(**common_args)
    else:
        raise ValueError(f"Unknown plot_type: {plot_type}")

    fig.update_layout(
        xaxis_title="Grid Source",
        yaxis_title=metric_col.replace("_", " ").title(),
        legend_title="Source",
        font=dict(family="Arial", size=14)
    )
    
    return fig

def plot_metric_histogram(
    df: pd.DataFrame, 
    metric_col: str, 
    title: Optional[str] = None
) -> go.Figure:
    """
    Generate an overlaid histogram/KDE.
    """
    if df.empty:
        return go.Figure().add_annotation(text="No Data Available", showarrow=False)

    sources = df["source"].unique()
    color_discrete_map = get_color_map(sources)

    fig = px.histogram(
        df, 
        x=metric_col, 
        color="source", 
        barmode="overlay", 
        marginal="box",
        color_discrete_map=color_discrete_map,
        title=title or f"Histogram of {metric_col}",
        template="plotly_white",
        opacity=0.6
    )

    fig.update_layout(
        xaxis_title=metric_col.replace("_", " ").title(),
        yaxis_title="Count",
        legend_title="Source",
        font=dict(family="Arial", size=14)
    )

    return fig

def plot_scatter_comparison(
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    size_col: Optional[str] = None,
    title: Optional[str] = None
) -> go.Figure:
    """
    Scatter plot for correlation analysis.
    """
    if df.empty:
        return go.Figure().add_annotation(text="No Data Available", showarrow=False)

    sources = df["source"].unique()
    color_discrete_map = get_color_map(sources)
    
    hover_data = [c for c in ["grid_result_id", "kcid", "bcid"] if c in df.columns]

    fig = px.scatter(
        df,
        x=x_col,
        y=y_col,
        size=size_col,
        color="source",
        color_discrete_map=color_discrete_map,
        hover_data=hover_data,
        title=title or f"{y_col} vs {x_col}",
        template="plotly_white",
        opacity=0.7
    )

    return fig
