"""
Feature analysis plotting functions.

This module contains functions for visualizing feature analysis, including correlation matrices,
factor analysis, PCA, and sample distributions.
"""

from math import pi
from typing import Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.express as px
import seaborn as sns
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from sklearn import preprocessing
from sklearn.cluster import KMeans
from sklearn.decomposition import FactorAnalysis, PCA
from sklearn.metrics import calinski_harabasz_score, davies_bouldin_score
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler
from sklearn_extra.cluster import KMedoids

from src.config_loader import TUMPalette, TUMPalette1
from src.config_loader import LIST_OF_CLUSTERING_PARAMETERS, REGIO7_REGIO5_GEM_DICT


def plot_correlation_matrix(
    corr: pd.DataFrame,
    ax: Optional[plt.Axes] = None,
    figsize: Tuple[int, int] = (9, 9),
    save_path: Optional[str] = None
) -> Figure:
    """
    Plot correlation matrix as a heatmap.

    Parameters
    ----------
    corr : pd.DataFrame
        Correlation matrix to visualize.
    ax : matplotlib.axes.Axes, optional
        Axes object for subplot integration. If None, creates a new figure.
    figsize : tuple of int, optional
        Figure size in inches (width, height). Default: (9, 9).
    save_path : str, optional
        Path to save the figure. If None, displays the plot.

    Returns
    -------
    matplotlib.figure.Figure
        The Figure object containing the correlation matrix plot.
    """
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.get_figure()

    sns.heatmap(corr, annot=True, fmt='.2f',
                cmap=plt.get_cmap('coolwarm'), cbar=True, ax=ax, vmin=-1, vmax=1)
    ax.set_yticklabels(ax.get_yticklabels(), rotation='horizontal')

    if save_path:
        fig.savefig(save_path, dpi=600)

    return fig


def plot_samples_per_regiostarclass(
    df_samples: pd.DataFrame,
    ax: Optional[plt.Axes] = None,
    figsize: Tuple[int, int] = (9, 6)
) -> Figure:
    """
    Plot bar chart showing number of samples per regiostar 7 class.

    Parameters
    ----------
    df_samples : pd.DataFrame
        DataFrame containing sample data with 'regio7' column.
    ax : matplotlib.axes.Axes, optional
        Axes object for subplot integration.
    figsize : tuple of int, optional
        Figure size in inches (width, height). Default: (9, 6).

    Returns
    -------
    matplotlib.figure.Figure
        The Figure object containing the bar chart.
    """
    if ax is None:
        fig = plt.figure(figsize=figsize)
        ax = fig.gca()
    else:
        fig = ax.get_figure()

    ax = sns.countplot(data=df_samples, x="regio7", palette=TUMPalette1, ax=ax)
    ax.bar_label(ax.containers[0])
    ax.set_xlabel('Regiostar 7 Klasse', fontsize=18)
    ax.set_ylabel('Anzahl der Stichproben', fontsize=18)
    ax.tick_params(axis='both', which='major', labelsize=16)

    return fig


def plot_samples_on_map(df_samples: pd.DataFrame) -> None:
    """
    Plot PLZ samples on an interactive plotly map.

    Parameters
    ----------
    df_samples : pd.DataFrame
        DataFrame containing sample data with 'lat', 'lon', and 'regio7' columns.
    """
    df_samples = df_samples.copy()
    df_samples['regio7_str'] = df_samples['regio7'].astype("str")
    fig = px.scatter_mapbox(
        df_samples, lat="lat", lon="lon",
        color="regio7_str", size="regio7", size_max=10, zoom=7
    )
    fig.update_layout(width=1000, height=900, margin={"r": 5, "t": 0, "l": 5, "b": 0})
    fig.update_layout(mapbox_style="light")
    fig.show()


def plot_factor_analysis(
    df_plz_parameters: pd.DataFrame,
    n_comps: int,
    figsize: Tuple[int, int] = (10, 8)
) -> Figure:
    """
    Plot factor analysis comparison for different methods.

    Parameters
    ----------
    df_plz_parameters : pd.DataFrame
        Set of parameters for grids.
    n_comps : int
        Number of components for factor analysis.
    figsize : tuple of int, optional
        Figure size in inches (width, height). Default: (10, 8).

    Returns
    -------
    matplotlib.figure.Figure
        The Figure object containing the factor analysis plots.
    """
    # Scale data
    data = df_plz_parameters
    X = StandardScaler().fit_transform(data)
    feature_names = data.columns

    # Define methods
    methods = [
        ("PCA", PCA()),
        ("Unrotated FA", FactorAnalysis()),
        ("Varimax FA", FactorAnalysis(rotation="varimax")),
    ]
    fig, axes = plt.subplots(ncols=len(methods), figsize=figsize, sharey=True)

    # Plot each method
    for ax, (method, fa) in zip(axes, methods):
        fa.set_params(n_components=n_comps)
        fa.fit(X)
        components = fa.components_.T

        vmax = 1
        ax.imshow(components, cmap="RdBu_r", vmax=vmax, vmin=-vmax)
        ax.set_yticks(np.arange(len(feature_names)))
        ax.set_yticklabels(feature_names)
        ax.set_title(str(method))
        ax.set_xticks(range(0, n_comps))

    fig.suptitle("Factors")
    plt.tight_layout()

    return fig


def get_parameters_for_clustering(df_plz_parameters: pd.DataFrame, n_comps: int) -> list:
    """
    Calculate mathematically ideal set of parameters using varimax rotated factor analysis.

    Parameters
    ----------
    df_plz_parameters : pd.DataFrame
        Set of parameters for grids.
    n_comps : int
        Number of components for factor analysis.

    Returns
    -------
    list
        List of selected parameters for clustering.
    """
    data = df_plz_parameters
    X = StandardScaler().fit_transform(data)
    feature_names = data.columns
    fa = FactorAnalysis(rotation="varimax")
    fa.set_params(n_components=n_comps)
    fa.fit(X)

    df_components_fa = pd.DataFrame(fa.components_.T, index=feature_names)
    parameters = []
    for column in df_components_fa:
        parameter = df_components_fa[column].abs().idxmax()
        parameters.append(parameter)
        print(parameter)

    return parameters


def plot_eigendecomposition(
    df_plz_parameters: pd.DataFrame,
    figsize: Tuple[int, int] = (10, 6)
) -> Figure:
    """
    Plot explained variance of principal components.

    Parameters
    ----------
    df_plz_parameters : pd.DataFrame
        Set of parameters for grids.
    figsize : tuple of int, optional
        Figure size in inches (width, height). Default: (10, 6).

    Returns
    -------
    matplotlib.figure.Figure
        The Figure object containing the eigendecomposition plot.
    """
    X_train = df_plz_parameters
    sc = StandardScaler()
    sc.fit(X_train)
    X_train_std = sc.transform(X_train)

    pca = PCA()
    X_train_pca = pca.fit_transform(X_train_std)
    exp_var_pca = pca.explained_variance_ratio_
    cum_sum_eigenvalues = np.cumsum(exp_var_pca)

    fig = plt.figure(figsize=figsize)
    plt.bar(range(0, len(exp_var_pca)), exp_var_pca, alpha=0.5, align='center',
            label='Erklärte Varianz der einzelnen Faktoren')
    plt.step(range(0, len(cum_sum_eigenvalues)), cum_sum_eigenvalues, where='mid',
             label='Kumulativ erklärte Varianz')
    plt.ylabel('Anteil der erklärten Varianz')
    plt.xlabel('Index des Faktors')
    plt.legend(loc='best')
    plt.tight_layout()

    return fig


