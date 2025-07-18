#!/usr/bin/env python
# coding: utf-8


# ==========================================================
# Part 1 : Imports
# ==========================================================


# 1.1 Standard library imports
import os
import gc
import time
import logging
from typing import Callable, Tuple, List, Dict, Optional
from collections import defaultdict, Counter
from datetime import datetime
from pathlib import Path
from itertools import groupby
import threading
import gzip
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm


# 1.2 Third-party library imports
import numpy as np
from scipy.stats import gamma
import pyarrow as pa
import pyarrow.parquet as pq
import matplotlib.pyplot as plt


# 1.3 Matplotlib configuration
plt.rcParams['font.size'] = 8


# ================================================
# Part 2.1 : General functions
# ================================================


# 2.1.1 : Dictionaries


def add_dicts(dict1: Dict, dict2: Dict) -> Dict:
    """
    Merge two dictionaries by summing their values for common keys.

    Args:
        dict1 (dict): First dictionary with numeric values.
        dict2 (dict): Second dictionary with numeric values.

    Returns:
        dict: A new dictionary with keys from both dictionaries, 
              where the values are the sum of the values from dict1 and dict2.
    """
    merged_dict = defaultdict(int)

    # Add values from dict1 to merged_dict
    for key, value in dict1.items():
        merged_dict[key] += value

    # Add values from dict2 to merged_dict
    for key, value in dict2.items():
        merged_dict[key] += value

    return dict(merged_dict)


def compute_mean_from_dict(input_dict: dict) -> dict:
    """
    Compute the mean of all list values in a dictionary.

    Args:
        input_dict (dict): Dictionary where keys map to lists of numeric values.

    Returns:
        dict: A new dictionary with the same keys, where each value is the mean
              of the corresponding list from the input dictionary.
    """
    mean_dict = {}
    for key, values in input_dict.items():
        if isinstance(values, list):
            mean_dict[key] = np.mean(np.array(values))
    return mean_dict


# 2.1.2 : Calculations


def calculate_distribution(
    data: np.ndarray, 
    first_bin: float, 
    last_bin: float, 
    bin_width: float
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Calculate the normalized distribution of data using a histogram.

    Args:
        data (np.ndarray): Array of data values to compute the distribution for.
        first_bin (float): Lower bound of the first bin.
        last_bin (float): Upper bound of the last bin.
        bin_width (float): Width of each bin.

    Returns:
        Tuple[np.ndarray, np.ndarray]:
            - points (np.ndarray): Array of bin centers.
            - distrib (np.ndarray): Normalized distribution (sum equals 1).
    """

    # Handle empty data array
    if data.size == 0: 
        return np.array([]), np.array([])

    # Points and not bins
    bins_array = np.arange(first_bin, last_bin + bin_width, bin_width)
    distrib, bins_edges = np.histogram(data, bins=bins_array)

    # Normalizing without generating NaNs
    if np.sum(distrib) > 0:
        distrib = distrib / np.sum(distrib)
    else:
        distrib = np.zeros_like(distrib)

    points = (bins_edges[:-1] + bins_edges[1:]) / 2

    # Return the bin centers and the normalized distribution
    return points, distrib


def linear_fit(values: np.ndarray, time_step: float, start_index: int, end_index: int) -> float:
    """
    Calculate the slope of a linear regression constrained to pass through the origin (0, 0),
    on a selected interval of the array.

    Args:
        values (np.ndarray): Input 1D array of values.
        time_step (float): Step size between x points.
        start_index (int): Starting index (inclusive).
        end_index (int): Ending index (inclusive).

    Returns:
        float: Slope of the linear regression.
    """
    x = np.arange(start_index, end_index + 1) * time_step
    y = values[start_index:end_index + 1]  # slice instead of comma

    x = x[:, np.newaxis]  # reshape for least squares
    slope, _, _, _ = np.linalg.lstsq(x, y, rcond=None)
    return slope[0]


def hist_on_columns(array_2d: np.ndarray, bin_width=1e1, bin_max=1e4) -> np.ndarray:
    """
    Compute a normalized histogram for each column of a 2D array.

    Args:
        array_2d (np.ndarray): 2D array where each column contains a distribution of values.

    Returns:
        np.ndarray: 2D array where each row corresponds to the normalized histogram of a column.
    """
    bin_edges = np.arange(0, bin_max + 2, bin_width)

    n_columns = array_2d.shape[1]
    histograms = np.empty(n_columns, dtype=object)

    for col_index in range(n_columns):
        counts, _ = np.histogram(array_2d[:, col_index], bins=bin_edges)
        histograms[col_index] = counts / np.sum(counts)

    return np.vstack(histograms)


# ================================================
# Part 2.2 : Probability functions
# ================================================


def proba_tataki(R: float, L: float, lp: float) -> float:
    """
    Compute the probability density function (PDF) for a given model.

    Args:
        R (float): Radial distance or observed value.
        L (float): Characteristic length scale of the system.
        lp (float): Persistence length of the system.

    Returns:
        float: Probability density function value for the given parameters.

    Notes:
        - This function models a probability based on a mathematical expression involving
          parameters `R`, `L`, and `lp`.
        - The calculation includes terms like the persistence length (`lp`) and 
          radial distance to length ratio (`R/L`).
    """
    # Compute auxiliary parameters
    t = (3 * L) / (2 * lp)
    alpha = (3 * t) / 4

    # Compute the normalization factor (N)
    N = (4 * (alpha ** (3 / 2))) / (((np.pi) ** (3 / 2)) * (4 + (12 * alpha ** (-1)) + 15 * (alpha ** (-2))))

    # Set constant A (scaling factor)
    A = 1

    # Compute the probability density function
    PLR = A * ((4 * np.pi * N) * ((R / L) ** 2)) / (L * ((1 - (R / L) ** 2)) ** (9 / 2)) \
          * np.exp(alpha - (3 * t) / (4 * (1 - (R / L) ** 2)))

    return PLR


def proba_gamma(mu: float, theta: float, L: float) -> float:
    """
    Compute the probability density function (PDF) of a Gamma distribution.

    Args:
        mu (float): Mean of the Gamma distribution.
        theta (float): Standard deviation of the Gamma distribution.
        L (float): Value at which to evaluate the probability density.

    Returns:
        float: Probability density at the given value L for the Gamma distribution.
    """
    alpha_gamma = mu**2 / theta**2                              # Calculate the shape parameter (alpha) of the Gamma distribution
    beta_gamma = theta**2 / mu                                  # Calculate the scale parameter (beta) of the Gamma distribution
    p_gamma = gamma.pdf(L, a=alpha_gamma, scale=beta_gamma)     # Compute the probability density for the value L

    p_gamma = p_gamma / np.sum(p_gamma)

    return p_gamma


# ================================================
# Part 2.3 : Landscape Functions
# ================================================


def generate_accessible_landscape(alphaf: float, length: int, nt: int) -> np.ndarray:
    """
    Generate a dynamic landscape where alpha is constant over time and space.

    Args:
        alphaf (float): Constant alpha value at each position.
        length (int): Number of spatial positions.
        nt (int): Number of time steps.

    Returns:
        np.ndarray: 2D array of shape (nt, length), filled with alphaf.
    """
    return np.full((nt, length), fill_value=alphaf, dtype=np.float32)


def calculate_landscape(
    alpha_choice: str,
    alphaf: float,
    d: int,
    D: int,
    alphao: float,
    gap: int,
    rap1_l: int,
    lacO_l: int,
    N: int,
    bpmin: int,
    nt: int
) -> np.ndarray:
    """
    Generate a time-evolving alpha landscape based on Marcand-style obstacle pattern rules.

    Args:
        alpha_choice (str): Strategy to construct the alpha landscape. One of ['array', 'LacI', 'constant_max'].
        alphaf (float): Alpha value in free regions.
        d (int): Number of initial free units (left padding).
        D (int): Number of final free units (right padding).
        alphao (float): Alpha value in obstacle regions.
        gap (int): Free units between obstacles (used in 'array' mode).
        rap1_l (int): Number of obstacle units per Rap1 block.
        lacO_l (int): Number of obstacle units per LacI block.
        N (int): Number of obstacle domains.
        bpmin (int): Minimum number of consecutive alphaf to be considered valid for tge binding of condensin.
        nt (int): Number of trajectories.

    Returns:
        np.ndarray: Alpha landscape of shape (nt, total_length)
    """

    # Unit (used for 'constant' and 'constant_max' cases)
    unit = np.array(
        d * [alphaf] +
        (rap1_l * [alphao] + [alphaf] + rap1_l * [alphao] + gap * [alphaf]) * (int(N - 1)) +
        (rap1_l * [alphao] + [alphaf] + rap1_l * [alphao]) +
        D * [alphaf]
    )
    unit_length = len(unit)
    unit_mean = np.mean(unit)

    # ---- I : array of gap ---- #
    if alpha_choice == 'array':
        landscape = np.tile(unit, (nt, 1))

    # ---- II : array with LacI ---- #
    elif alpha_choice == 'LacI':
        base_pattern = (
            d * [alphaf] +
            (rap1_l * [alphao] + [alphaf] + rap1_l * [alphao] +
             3 * [alphaf] + lacO_l * [alphao] + 8 * [alphaf]) * (int(N - 1)) +
            (rap1_l * [alphao] + [alphaf] + rap1_l * [alphao]) +
            D * [alphaf]
        )
        landscape = np.tile(np.array(base_pattern), (nt, 1))

    # ---- III : Constant value (mean) ---- #
    elif alpha_choice == 'constant':
        landscape = np.full((nt, unit_length), fill_value=unit_mean)

    # ---- IV : Constant max value ---- #
    elif alpha_choice == 'constant_max':
        landscape = np.full((nt, unit_length), fill_value=alphaf)

    else:
        raise ValueError(
            f"Invalid alpha_choice: '{alpha_choice}'. Must be one of ['array', 'LacI', 'constant', 'constant_max']."
        )

    # Minimal condensin binding size
    if alpha_choice in ["array", "LacI"] :
        corrected_line = binding_length(landscape[0], alphaf, alphao, bpmin)
        landscape = np.tile(corrected_line, (nt, 1))

    return landscape


def binding_length(alpha_list: np.ndarray, alphao: float, alphaf: float, bpmin: int) -> np.ndarray:
    """
    Modifies sequences of consecutive `alphaf` values in an array if their length is less than `bpmin`.

    This function takes an input array `alpha_list` and checks for sequences of consecutive
    elements equal to `alphaf`. If the length of any such sequence is less than `bpmin`,
    all values in that sequence are replaced with `alphao`.

    Parameters:
    -----------
    alpha_list : np.ndarray
        The input array of numerical values to process.
    alphao : float
        The value to replace sequences with if their length is less than `bpmin`.
    alphaf : float
        The value representing sequences of interest in the array.
    bpmin : int
        The minimum length of a sequence of `alphaf` required to remain unchanged.

    Returns:
    --------
    np.ndarray
        A new array where sequences of `alphaf` with a length smaller than `bpmin`
        have been replaced by `alphao`.

    Example:
    --------
    >>> alpha_list = np.array([0, 0, 1, 1, 0, 0, 0, 1, 1, 0, 0, 1, 0, 1, 0, 0, 1, 0])
    >>> alphao = 0
    >>> alphaf = 1
    >>> bpmin = 2
    >>> binding_length(alpha_list, alphao, alphaf, bpmin)
    array([0, 0, 1, 1, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    """
    alpha_array = alpha_list.copy()     # Avoid modifying the original input array
    mask = alpha_array == alphaf        # Identify indices where the values are equal to `alphaf`

    # Find start and end indices of consecutive sequences of `alphaf`
    diffs = np.diff(np.concatenate(([0], mask.astype(int), [0])))
    starts = np.where(diffs == 1)[0]    # Start of sequences
    ends = np.where(diffs == -1)[0]     # End of sequences

    # Iterate over sequences and replace if the length is less than `bpmin`
    for start, end in zip(starts, ends):
        length = end - start
        if length < bpmin:
            alpha_array[start:end] = alphao

    return alpha_array


def find_blocks(array: np.ndarray, alpha_value: float) -> List[Tuple[int, int]]:
    """
    Identify contiguous regions in the array where values are equal (or close) to a given value.
    Can be used to find obstacles and linkers !

    Parameters
    ----------
    array : np.ndarray
        The array representing the full environment.
    
    value : float
        The value considered as an obstacle (using approximate comparison).

    Returns
    -------
    List[Tuple[int, int]]
        A list of intervals (start_index, end_index) for each contiguous obstacle block.
    """
    array = np.asarray(array)
    is_block = np.isclose(array, alpha_value, atol=1e-8)
    diff = np.diff(is_block.astype(int))
    starts = np.where(diff == 1)[0] + 1
    ends = np.where(diff == -1)[0] + 1

    if is_block[0]:
        starts = np.insert(starts, 0, 0)
    if is_block[-1]:
        ends = np.append(ends, len(array))

    return list(zip(starts, ends))


def find_interval_containing_value(
    intervals: List[Tuple[int, int]], value: int
) -> Optional[Tuple[int, int]]:
    """
    Return the first interval (start, end) that contains the specified value.

    Parameters
    ----------
    intervals : List[Tuple[int, int]]
        A list of intervals (start, end) sorted or unsorted.
    
    value : int
        The index or position to locate within the intervals.

    Returns
    -------
    Optional[Tuple[int, int]]
        The interval that contains the value, or None if not found.
    """
    intervals_array = np.array(intervals)
    mask = (intervals_array[:, 0] <= value) & (value < intervals_array[:, 1])

    
    if np.any(mask):
        return tuple(intervals_array[mask][0])
    return None


# ==========================================================
# Part 2.4 : Modelling Functions
# ==========================================================


def perform_jump(origin: int, cumulative_probabilities: np.ndarray) -> int:
    """
    Perform a jump based on cumulative probabilities.

    Args:
        origin (int): Starting position.
        cumulative_probabilities (np.ndarray): Cumulative probability array.

    Returns:
        int: New position after jump.
    """
    r = np.random.rand()
    j = 0
    while j < len(cumulative_probabilities) and r >= cumulative_probabilities[j]:
        j += 1
    return origin + j


def attempt_binding(alpha: float) -> bool:
    """
    Determine whether a binding attempt is successful based on alpha.

    Args:
        alpha (float): Binding probability.

    Returns:
        bool: True if binding succeeds, False otherwise.
    """
    return np.random.rand() < alpha


def attempt_unhooking(beta: float) -> bool:
    """
    Determine whether unhooking occurs based on beta.

    Args:
        beta (float): Probability of unhooking.

    Returns:
        bool: True if unhooking occurs, False otherwise.
    """
    return np.random.rand() < beta


def decide_execution_order() -> bool:
    """
    Randomly choose between two execution orders.

    Returns:
        bool: True if order 1 is chosen, False otherwise.
    """
    return np.random.choice([1, 2]) == 1


def sample_gillespie_delay(rate_total: float) -> float:
    """
    Sample a time delay from an exponential distribution using Gillespie algorithm.

    Args:
        rate_total (float): Total rate of reactions.

    Returns:
        float: Sampled delay time.
    """
    return -np.log(np.random.rand()) / rate_total


def folding(landscape:np.ndarray, first_origin:int) -> int:
    """
    Jumping on a random place around the origin, for the first position of the simulation.

    Args:
        landscape (np.ndarray): landscape with the minimum size for condensin to bind.
        origin (int): first point on which condensin arrives.

    Returns:
        int: The real origin of the simulation
    """

    # In order to test but normally we'll never begin any simulation on 0
    if first_origin == 0 :
        true_origin = 0

    else :
        # Constant scenario : forcing the origin -> Might provoc a problem if alphaf and alphao are not 0 or 1 anymore !
        if landscape[first_origin] != 1 and landscape[first_origin] != 0 :
            true_origin = first_origin        

        # Falling on a 1 : Validated
        if landscape[first_origin] == 1 :
            true_origin = first_origin

        # Falling on a 0 : Refuted
        if landscape[first_origin] == 0 :
            back_on_obstacle = 1
            while landscape[first_origin-back_on_obstacle] != 1 :
                back_on_obstacle += 1
            pos = first_origin - back_on_obstacle
            back_on_linker = 1
            while landscape[pos-back_on_linker] != 0 :
                back_on_linker += 1
            true_origin = np.random.randint(first_origin-(back_on_obstacle+back_on_linker), first_origin-back_on_obstacle)+1

    return(true_origin)


def compute_bootstrap_std(
    trajectories: list,
    nt: int,
    max_time: int,
    n_boot: int = 10000,
    batch_size: int = 100
) -> float:
    """
    Perform bootstrapping to compute standard deviation of fitted slopes.

    Args:
        trajectories (list): List of time series data.
        nt (int): Number of time steps per trajectory.
        max_time (int): Final time index for linear fitting.
        n_boot (int, optional): Number of bootstrap samples. Default is 10000.
        batch_size (int, optional): Number of samples per batch. Default is 100.

    Returns:
        float: Standard deviation of the bootstrap results.
    """
    np.random.seed()
    tab_array = np.array(trajectories)
    bootstrap_results = np.empty(n_boot)

    for i in range(0, n_boot, batch_size):
        current_batch_size = min(batch_size, n_boot - i)
        sample_indices = np.random.randint(0, nt, size=(current_batch_size, nt))
        samples = tab_array[sample_indices]
        means = np.mean(samples, axis=1)

        bootstrap_results[i:i + current_batch_size] = [
            linear_fit(values=mean, time_step=1, start_index=0, end_index=int(max_time))
            for mean in means
        ]

    result_std = np.std(bootstrap_results)

    # Clean memory
    del sample_indices, samples, bootstrap_results, means, tab_array
    gc.collect()

    return result_std


def gillespie_algorithm_in_position(
    lenght: int,
    l_max: int,
    x_max: int,
    origin: int,
    alpha_matrix: np.ndarray,
    p: np.ndarray,
    beta: float,
    nt: int,
) -> tuple[np.ndarray, list, list, float]:
    """
    Simulate a stochastic Gillespie algorithm with a custom reaction landscape over multiple trajectories.

    Args:
        lenght (int): Total length of the spatial domain.
        l_max (int): Maximum jump length.
        x_max (int): Maximum x position (stopping condition).
        origin (int): Starting x-position.
        alpha_list (np.ndarray): Matrix (nt x total_length) of alpha values.
        p (np.ndarray): Cumulative jump probability array.
        beta (float): Unhooking probability per position.
        nt (int): Number of independent trajectories to simulate.

    Returns:
        tuple:
            - results (np.ndarray): Matrix of shape (nt, x_max + 1), containing time values.
            - all_t (list): List of time series for each trajectory.
            - all_x (list): List of x position series for each trajectory.
            - t_max (float): Maximum time reached across all trajectories.
    """

    # --- Starting values --- #

    beta_matrix = np.tile(np.full(lenght, beta), (nt, 1))
    t_matrix = np.empty(nt, dtype=object)
    x_matrix = np.empty(nt, dtype=object)
    
    # Main result matrix (time values per position)
    results = np.full((nt, x_max + 1), np.nan, dtype=float)

    # --- Loop on trajectories --- #
    for n_idx in range(nt):
        results[n_idx][0] = 0  # initial time at x=0

        t = 0
        i = 0
        i0 = 0
        x = folding(alpha_matrix[n_idx], origin)

        t_series = [t]
        x_series = [x - origin]

        # --- Reaction loop --- #
        while x < x_max:
            # Total reaction rate at position x
            r_tot = beta_matrix[n_idx][x] + np.nansum(
                p[1:(l_max - x)] * alpha_matrix[n_idx][(x + 1):l_max]
            )

            # Sample next reaction time
            t += -np.log(np.random.rand()) / r_tot
            if np.isinf(t) == True:
                t = 1e308

            # Unhooking test
            r0 = np.random.rand()
            if r0 < beta_matrix[n_idx][x] / r_tot:
                i = int(np.floor(x))
                results[n_idx][i0:int(min(np.floor(x_max), i) + 1)] = t
                break

            # Jump decision
            di = 1  # jump starts at 1 (p[0] = 0 by design)
            rp = beta_matrix[n_idx][x] + p[di] * alpha_matrix[n_idx][x + di]

            while (rp / r_tot) < r0 and (di < l_max - 1 - x):
                di += 1
                rp += p[di] * alpha_matrix[n_idx][x + di]

            # Update position
            x += di
            t_series.append(t)
            x_series.append(x - origin)

            # Fill time array
            i = int(np.floor(x)) if not np.isinf(x) else x_max
            results[n_idx][i0:int(min(np.floor(x_max), i) + 1)] = t
            i0 = i + 1

        t_matrix[n_idx] = t_series
        x_matrix[n_idx] = x_series

    # Compute max time across all trajectories
    t_max = np.floor(max(max(t_series) for t_series in t_matrix))

    return results, t_matrix, x_matrix, t_max


# ==========================================================
# Part 2.5 : Analysis Functions
# ==========================================================


def calculate_obs_and_linker_distribution(
    alpha_array: np.ndarray, alphao: float, alphaf: float, step: int = 10
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Process a 1D alpha array to calculate lengths of linker and obstacle sequences
    and their distributions.

    Args:
        alpha_array (np.ndarray): 1D array representing linkers (alphaf) and obstacles (alphao).
        alphao (float): Value representing the obstacles.
        alphaf (float): Value representing the linkers.
        step (int): Step size for the distribution calculation (default is 1).

    Returns:
        Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
            - points_o (np.ndarray): Centers of bins for obstacle lengths.
            - distrib_o (np.ndarray): Normalized distribution of obstacle lengths.
            - points_l (np.ndarray): Centers of bins for linker lengths.
            - distrib_l (np.ndarray): Normalized distribution of linker lengths.
    """
    # Masks for obstacles and linkers
    mask_o = alpha_array == alphao
    mask_l = alpha_array == alphaf

    # Find lengths of obstacle sequences
    diffs_o = np.diff(np.concatenate(([0], mask_o.astype(int), [0])))
    starts_o = np.where(diffs_o == 1)[0]
    ends_o = np.where(diffs_o == -1)[0]
    counts_o = ends_o - starts_o

    # Find lengths of linker sequences
    diffs_l = np.diff(np.concatenate(([0], mask_l.astype(int), [0])))
    starts_l = np.where(diffs_l == 1)[0]
    ends_l = np.where(diffs_l == -1)[0]
    counts_l = ends_l - starts_l

    # Handle empty counts
    if counts_o.size == 0:
        points_o, distrib_o = np.array([]), np.array([])
    else:
        points_o, distrib_o = calculate_distribution(data=counts_o, first_bin=0, last_bin=np.max(counts_o)+step, bin_width=step)

    if counts_l.size == 0:
        points_l, distrib_l = np.array([]), np.array([])
    else:
        points_l, distrib_l = calculate_distribution(data=counts_l, first_bin=0, last_bin=np.max(counts_l)+step, bin_width=step)

    # Returns the distribution on one array !
    return points_o, distrib_o, points_l, distrib_l


def calculate_main_results_marcand(
    results: np.ndarray,
    alpha_matrix: np.ndarray,
    x_max: int,
    x_min: int,
    mu: float,
    plot_results: bool = False
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float, np.ndarray]:
    """
    Calculate all main metrics from Marcand-style simulations.

    Args:
        results (np.ndarray): Time matrix of shape (n_trajectories, x_max + 1).
        alpha_matrix (np.ndarray): Landscape matrix (n_trajectories, length).
        x_max (int): Last position of the obstacle.
        x_min (int): First position of the obstacle.
        origin (int): Initial position of the simulation.
        results_wo (np.ndarray): Results from the control (without obstacle).
        plot_results (bool, optional): If True, saves various plots. Default is False.

    Returns:
        tuple: Contains the following computed results:
            - fpt_mean (np.ndarray): Mean first passage time at each position.
            - fpt_2D (np.ndarray): Histogram matrix of all FPTs, normalized per column.
            - fpt_xmax_distribution (np.ndarray): Distribution of first passage times at x_max.
            - p_tau (np.ndarray): Cumulative probability of not yet passed (1 - CDF).
            - v_marcand (float): Effective velocity across the obstacle region.
            - delay (np.ndarray): Difference in FPT between obstacle and control.
    """
    
    # Set FPT at origin to 0 for all trajectories
    results[:, 0] = 0

    # Extract normalized obstacle profile from alpha
    obs_profile = alpha_matrix[0, int(x_min):int(x_max)]
    obs_normalized = obs_profile / obs_profile.sum()

    # 1. Mean first passage time across trajectories
    fpt_mean = np.nanmean(results, axis=0)

    # 2. 2D histogram of all FPTs (per column)
    fpt_2D = hist_on_columns(results)

    # 3. Histogram of first passage times at x_max
    fpt_xmax_distribution = fpt_2D[-1]

    # 4. Cumulative probability of passage
    p_tau = 1 - np.cumsum(fpt_xmax_distribution)

    # 5. Effective velocity (mean slope over obstacle region)
    v_th = 1 / mu
    fpt_wo_xmin = v_th * x_min
    fpt_wo_xmax = v_th * x_max
    fpt_mean_xmax = fpt_mean[int(x_max)]
    v_marcand = (fpt_mean_xmax - fpt_wo_xmin) / (fpt_wo_xmax - fpt_wo_xmin)

    # obstacle_length = x_max - x_min
    # random_pos = np.random.randint(int(x_min / 4), int(x_min / 2) + 1)
    # lower_bound = random_pos - obstacle_length
    # upper_bound = random_pos + obstacle_length
    # baseline_slope = linear_fit(
    #     values=fpt_mean,
    #     time_step=1,
    #     start_index=lower_bound,
    #     end_index=upper_bound
    # )
    # v_marcand = (fpt_mean[int(x_max)] - fpt_mean[int(x_min)]) / baseline_slope


    # 6. Delay: how much the obstacle slows things down
    # delay = fpt_mean - np.nanmean(results_wo, axis=0)
    delay = fpt_mean - np.mean(v_th * np.arange(0, len(results[0]), 1), axis=0)

    # -------------------- Optional plots -------------------- #
    if plot_results:

        plt.figure("landscape")
        plt.plot(alpha_matrix[0])
        plt.title("Alpha Landscape")
        plt.savefig("landscape.png")

        plt.figure("fpt_mean")
        plt.plot(fpt_mean)
        plt.title("Mean First Passage Time")
        plt.savefig("fpt_mean.png")

        plt.figure("fpt_2D")
        plt.imshow(fpt_2D.T, aspect='auto', origin='lower')
        plt.title("FPT Distribution (2D Histogram)")
        plt.colorbar(label="Probability")
        plt.savefig("fpt_2D.png")

        plt.figure("fpt_xmax_distribution")
        plt.plot(fpt_xmax_distribution)
        plt.title("FPT Distribution at x_max")
        plt.savefig("fpt_xmax_distribution.png")

        plt.figure("p_tau")
        plt.plot(p_tau)
        plt.title("Cumulative Probability of Passage")
        plt.savefig("p_tau.png")

        plt.figure("delay")
        plt.plot(delay)
        plt.title("Delay Induced by Obstacle")
        plt.savefig("delay.png")

        plt.close("all")

    return fpt_mean, fpt_2D, fpt_xmax_distribution, p_tau, v_marcand, delay


def calculate_position_histogram(results: list, Lmax: int, origin: int, tmax: int, time_step: int = 1) -> np.ndarray:
    """
    Calculate the position histogram for a set of results over time.

    Args:
        results (list): A list of trajectories, where each trajectory is a list of positions over time.
        Lmax (int): Maximum length of the domain.
        origin (int): Offset or starting position for the domain.
        tmax (int): Maximum time for the simulation.
        time_step (int, optional): Time step interval for calculating histograms. Defaults to 1.

    Returns:
        np.ndarray: A 2D array representing the normalized histogram of positions over time.
            Rows correspond to bins, and columns correspond to time steps.

    Notes:
        - The domain is divided into bins ranging from 0 to `Lmax - 2 * origin`.
        - Histograms are calculated for each time step, and the resulting counts are normalized to probabilities.
        - If no data exists for a time step, the corresponding histogram is filled with zeros.
    """

    results_transposed = np.array(results).T                # Transpose the results to process positions at each time step
    num_bins = np.arange(0, Lmax - (2 * origin) + 1, 1)     # Define the bins for the histogram
    histograms = [None] * (tmax // time_step)               # Initialize the list for histograms

    # Calculate the histogram for each time step
    for t in range(0, tmax, time_step):
        bin_counts, _ = np.histogram(results_transposed[t], bins=num_bins)
        histograms[t] = bin_counts

    # Normalize the histograms to probabilities
    histograms_list = [arr.tolist() for arr in histograms]
    for t in range(0, tmax, time_step):
        total_count = np.sum(histograms_list[t])
        if total_count != 0:
            histograms_list[t] = np.divide(histograms_list[t], total_count)
        else:
            histograms_list[t] = np.zeros_like(histograms_list[t])

    # Convert the list of histograms to a NumPy array and transpose it
    histograms_array = np.copy(histograms_list).T

    return histograms_array


def calculate_distrib_tbjs(matrix_t : np.ndarray, last_bin: float = 1e5):
    """Calculate the distribution of times between jumps : tbj

    Args:
        matrix_t (list of lists): List of time steps for all trajectories.
        tmax (int): Maximum time value for the simulation.


    Returns:
        tuple: 
            - tbj_bins (np.ndarray): Array of bin edges for the time intervals.
            - tbj_distribution (np.ndarray): Normalized histogram of times between jumps.

    Notes:
        - The function computes time differences between consecutive jumps across all trajectories.
        - It returns a normalized histogram representing the distribution of these time differences.
        - If no data exists, the distribution is filled with zeros.
    """
    # Define bins
    tbj_bins = np.arange(0, last_bin + 1, 1)

    # Flatten matrix_t and compute time differences
    tbj_list = np.diff(np.concatenate(matrix_t))               # Differences between jumps

    # Create histogram
    tbj_distrib, _ = np.histogram(tbj_list, bins=tbj_bins)     # Compute histogram

    # Normalize the distribution
    if np.sum(tbj_distrib) != 0:
        tbj_distrib = tbj_distrib / np.sum(tbj_distrib)  
    else:
        tbj_distrib = np.zeros_like(tbj_distrib)

    # Return bin edges (excluding the last) and normalized distribution
    return tbj_bins[:-1], tbj_distrib


def calculate_fpt_matrix(matrix_t: np.ndarray, matrix_x: np.ndarray, tmax: int, t_bin: int, nt:int) -> tuple[np.ndarray, np.ndarray] :
    """
    Calculate the first passage time (FPT) density using bins to reduce memory usage.
    Positions are grouped into bins of 'bin_size'.

    Args:
        matrix_t (np.ndarray): All times.
        matrix_x (np.ndarray): All positions.
        tmax (int): Time maximum fixed.
        bin_size (int): Bin size of time.
        rf (int): Rounding Factor.

    Returns:
        tuple: 
            - fpt_results (np.ndarray): Matrix of density of first pass times.
            - fpt_number (np.ndarray): Number of trajectories that reached the positions.
    """
    
    x_max = int(np.max(np.concatenate(matrix_x)))
    n_bins = int(np.ceil(x_max / t_bin))
    fpt_matrix = np.zeros((int(tmax + 1), n_bins))
    translated_all_x = [[x - sublist[0] for x in sublist] for sublist in matrix_x]

    # I : matrix
    couples = np.concatenate([list(zip(x, [min(np.floor(ti), tmax) for ti in t])) for x, t in zip(translated_all_x, matrix_t)])
    for _ in range(len(couples)):
        if couples[_][0] != 0:
            time_index = int(couples[_][1])
            bin_index_start = int(couples[_ - 1][0]) // t_bin
            bin_index_end = int(couples[_][0]) // t_bin
            fpt_matrix[time_index][bin_index_start:bin_index_end ] += 1

    # II : curve
    fpt_number = np.sum(fpt_matrix, axis=0)
    not_fpt_number = nt - fpt_number
    fpt_matrix = np.vstack((fpt_matrix, not_fpt_number))
    fpt_results = fpt_matrix / np.sum(fpt_matrix, axis=0)  # normalizing with the line of absent trajectories

    return fpt_results, fpt_number


def calculate_instantaneous_statistics(
    matrix_t: np.ndarray, 
    matrix_x: np.ndarray, 
    nt: int, 
    first_bin: float = 0,
    last_bin: float = 1e5,
    bin_width: float = 1.0,
) -> Tuple[
    np.ndarray, np.ndarray, float, float, float, 
    np.ndarray, np.ndarray, float, float, float, 
    np.ndarray, np.ndarray, float, float, float
]:
    """
    Calculate statistics for instantaneous speeds across multiple trajectories.

    Args:
        matrix_t (np.ndarray): Times for all trajectories.
        matrix_x (np.ndarray): Positions for all trajectories.
        nt (int): Total number of trajectories.
        first_bin (float, optional): Lower bound for the histogram bins. Defaults to 0.
        last_bin (float, optional): Upper bound for the histogram bins. Defaults to 1e6.
        bin_width (float, optional): Width of bins for the speed distribution. Defaults to 1.0.

    Returns:
        tuple: 
            - dx_points (np.ndarray): Points (bin centers) for the displacement distribution (Δx).
            - dx_distrib (np.ndarray): Normalized displacement distribution (Δx).
            - dx_mean (float): Mean displacement (Δx).
            - dx_med (float): Median displacement (Δx).
            - dx_mp (float): Most probable displacement (Δx).
            - dt_points (np.ndarray): Points (bin centers) for the time interval distribution (Δt).
            - dt_distrib (np.ndarray): Normalized time interval distribution (Δt).
            - dt_mean (float): Mean time interval (Δt).
            - dt_med (float): Median time interval (Δt).
            - dt_mp (float): Most probable time interval (Δt).
            - v_points (np.ndarray): Points (bin centers) for the speed distribution.
            - v_distrib (np.ndarray): Normalized speed distribution.
            - v_mean (float): Mean of the instantaneous speeds.
            - v_med (float): Median of the instantaneous speeds.
            - v_mp (float): Most probable instantaneous speed.
    """

    # Initialize arrays for displacements, time intervals, and speeds
    dx_array = np.array([None] * nt, dtype=object)
    dt_array = np.array([None] * nt, dtype=object)
    vi_array = np.array([None] * nt, dtype=object)

    # Loop through each trajectory
    for i in range(nt):
        x = np.array(matrix_x[i])
        t = np.array(matrix_t[i])

        # Calculate displacements (Δx) and time intervals (Δt)
        dx = x[1:] - x[:-1]
        dt = t[1:] - t[:-1]

        # Calculate instantaneous speeds (Δx / Δt)
        dv = dx / dt

        # Store results in arrays
        dx_array[i] = dx
        dt_array[i] = dt
        vi_array[i] = dv

    # Concatenate arrays for all trajectories
    dx_array = np.concatenate(dx_array)
    dt_array = np.concatenate(dt_array)
    vi_array = np.concatenate(vi_array)

    # Calculate distributions for Δx, Δt, and speeds
    dx_points, dx_distrib = calculate_distribution(dx_array, first_bin, last_bin, bin_width)
    dt_points, dt_distrib = calculate_distribution(dt_array, first_bin, last_bin, bin_width)
    vi_points, vi_distrib = calculate_distribution(vi_array, first_bin, last_bin, bin_width)

    # Compute statistics (mean, median, most probable values)
    if vi_distrib.size > 0:
        dx_mean = np.mean(dx_array)
        dx_med = np.median(dx_array)
        dx_mp = dx_points[np.argmax(dx_distrib)]

        dt_mean = np.mean(dt_array)
        dt_med = np.median(dt_array)
        dt_mp = dt_points[np.argmax(dt_distrib)]

        vi_mean = np.mean(vi_array)
        vi_med = np.median(vi_array)
        vi_mp = vi_points[np.argmax(vi_distrib)]
    else:
        # Default values if distributions are empty
        dx_mean, dx_med, dx_mp = 0.0, 0.0, 0.0
        dt_mean, dt_med, dt_mp = 0.0, 0.0, 0.0
        vi_mean, vi_med, vi_mp = 0.0, 0.0, 0.0

    # Return results
    return (
        dx_points, dx_distrib, dx_mean, dx_med, dx_mp,
        dt_points, dt_distrib, dt_mean, dt_med, dt_mp,
        vi_points, vi_distrib, vi_mean, vi_med, vi_mp
    )


# ================================================
# Part 2.6 : Writing functions
# ================================================


def set_working_environment(base_dir: str = "marcand/outputs", subfolder: str = "") -> None:
    """
    Ensure the specified folder exists and change the current working directory to it.
        Check if the folder exists; if not, create it
        Change the current working directory to the specified folder

    Args:
        folder_path (str): Path to the folder where the working environment should be set.

    Returns:
        None.
    """
    root = os.getcwd()
    full_path = os.path.join(root, base_dir, subfolder)
    
    os.makedirs(full_path, exist_ok=True)
    os.chdir(full_path)

    return full_path


def prepare_value(value):
    """
    Convert various data types to Parquet-compatible formats, including deep handling of NaNs.

    Args:
        value: The value to be converted.

    Returns:
        The converted value in a compatible format.

    Raises:
        ValueError: If the data type is unsupported.
    """
    # Convert NumPy matrix or array to list
    if isinstance(value, (np.ndarray, np.matrix)):
        return [prepare_value(v) for v in np.array(value).tolist()]

    # Convert NumPy scalars to native scalars
    elif isinstance(value, (np.integer, np.floating)):
        if np.isnan(value):
            return None
        return value.item()

    # Handle float NaN explicitly
    elif isinstance(value, float) and np.isnan(value):
        return None

    # Convert list recursively
    elif isinstance(value, list):
        return [prepare_value(v) for v in value]

    # Scalars and strings
    elif isinstance(value, (int, float, str)):
        return value

    # Optional: allow None to pass through
    elif value is None:
        return None

    else:
        raise ValueError(f"Unsupported data type: {type(value)}")


def writing_parquet(file:str, title: str, data_result: dict) -> None:
    """
    Write a dictionary directly into a Parquet file using PyArrow.
    Ensures that all numerical values, arrays, and lists are properly handled.

    Note:
        - Each key in the Parquet file must correspond to a list or an array.
        - Compatible only with native Python types.
        - Even a number like 1.797e308 only takes up 8 bytes (64 bits) in the Parquet file.

    Args:
        title (str): The base name for the Parquet file and folder.
        data_result (dict): Dictionary containing the data to write. 
            Supported types for values:
                - NumPy arrays (converted to lists).
                - NumPy matrices (converted to lists).
                - NumPy scalars (converted to native Python types).
                - Python scalars (int, float).
                - Lists (unchanged).
                - Strings (unchanged).

    Returns:
        None: This function does not return any value.

    Raises:
        ValueError: If a value in the dictionary has an unsupported data type.
        Exception: If writing to the Parquet file fails for any reason.
    """

    # Define the Parquet file path
    data_file_name = os.path.join(title, f'{file}_{title}.parquet')

    # Prepare the data for Parquet
    prepared_data = {key: [prepare_value(value)] if not isinstance(value, list) else prepare_value(value)
                     for key, value in data_result.items()}

    try:        
        table = pa.table(prepared_data)                                         # Create a PyArrow Table from the dictionary
        pq.write_table(table, data_file_name, compression='gzip')               # Write the table to a Parquet file

    except Exception as e:
        print(f"Failed to write Parquet file due to: {e}")
    
    return None


def inspect_data_types(data: dict) -> None:
    """
    Inspect and print the types and dimensions of values in a dictionary.

    Args:
        data (dict): Dictionary containing the data to inspect. 
            Keys are expected to be strings, and values can be of various types, such as:
            - NumPy arrays (prints dimensions).
            - Lists (prints length).
            - Other types (prints the type of the value).

    Returns:
        None
    """
    for key, value in data.items():
        if isinstance(value, np.ndarray):
            print(f"Key: {key}, Dimensions: {value.shape}")     # Check if the value is a NumPy array
        elif isinstance(value, list):
            print(f"Key: {key}, Length: {len(value)}")          # Check if the value is a list
        else:
            print(f"Key: {key}, Type: {type(value)}")           # Other types
    return None


# ================================================
# Part 3.1 : Main function
# ================================================


def sw_marcand(alpha_choice, gap, bpmin, alphaf, alphao, mu, theta, origin, nt, path):


    # --- Initialization --- #

    # File
    title = f'alphachoice={alpha_choice}_gap={int(gap)}_mu={int(mu)}_theta={int(theta)}_nt={nt}'
    if not os.path.exists(title):
        os.mkdir(title)

    # Constants 
    N = 8            # number of groups of 2 obstacles : 16 in total
    rap1_l = 14     # size in base pairs of rap1 obstacles
    lacO_l = 24     # size in base pairs of lacO obstacles
    bps = 1                                                                                      # based pair step 1 per 1
    c_bp = 3                                                                                         # depends on naked dna or chromatin : 3 for naked vs 25 for chromatin
    lp_dna = 100                                                                                     # persistence lenght
    beta = 0                                                                                         # beta
    dt = 1                                                                                           # step of time

    
    # Chromatin    

    # Input values for the all landscape
    l_min = 0                                   # first point of chromatin
    x_min = 2000                                # first point of obstacle
    d = x_min - l_min                           # distance between first point of chromatin and first point of obstacle    
    D = x_min                                   # lenght after array

    # All landscape
    alpha_matrix = calculate_landscape(alpha_choice, alphaf, d, D, alphao, gap, rap1_l, lacO_l, N, bpmin, nt)
    alpha_mean = np.mean(alpha_matrix, axis=0)

    # Details
    lenght_array = len(alpha_matrix[0]) - d - D
    x_max = x_min + lenght_array
    l_max = len(alpha_matrix[0])

    # Total
    L = np.arange(l_min, l_max, bps)        # All chromatin positions / Probability distribution on this interval
    total_lenght = len(L)

    # Fixed analysis parameters
    bin_fpt = int(1)    # Bins on times during the all analysis
    tf = int(1000)      # Maximum times fixed in order to not map until 1e100

    
    # --- Simulation --- #

    # Landscape
    obs_points, obs_distrib, link_points, link_distrib = calculate_obs_and_linker_distribution(alpha_matrix[0], alphao, alphaf)

    # Probabilities
    p = proba_gamma(mu, theta, L)

    # Modelling
    results, t_matrix, x_matrix, tmax  = gillespie_algorithm_in_position(total_lenght, l_max, x_max, origin, alpha_matrix, p, beta, nt)

    # Results
    fpt_mean, fpt_2D, fpt_x_max_distrib, p_tau, v_marcand, delay = calculate_main_results_marcand(results, alpha_matrix, x_max, x_min, mu)

    # Times
    fpt_distrib_2D, fpt_number = calculate_fpt_matrix(t_matrix, x_matrix, tmax=tf, t_bin=bin_fpt, nt=nt)

    # Waiting times
    tbj_points, tbj_distrib = calculate_distrib_tbjs(t_matrix)

    # Speeds
    dx_points, dx_distrib, dx_mean, dx_med, dx_mp, dt_points, dt_distrib, dt_mean, dt_med, dt_mp, vi_points, vi_distrib, vi_mean, vi_med, vi_mp = calculate_instantaneous_statistics(t_matrix, x_matrix, nt)


    # --- Writing --- #

    # First cleaning
    del alpha_matrix, t_matrix, x_matrix
    gc.collect()

    # Composing the main result that will be written
    data_result = {
        'alpha_choice': alpha_choice, 'gap':gap, 'bpmin':bpmin, 'mu':mu, 'theta':theta, 
        'nt':nt, 'dt':dt, 'N':N, 
        'alphao': alphao, 'alphaf': alphaf, 'beta': beta, 
        'total_lenght':total_lenght, 'origin': origin, 'bps': bps,

        'alpha_mean': alpha_mean,
        'obs_points':obs_points, 'obs_distrib':obs_distrib,
        'link_points':link_points, 'link_distrib':link_distrib,

        'p':p,

        'results':results,
        'fpt_mean':fpt_mean, 'fpt_2D':fpt_2D, 'fpt_x_max_distrib':fpt_x_max_distrib, 'p_tau':p_tau, 'v_marcand':v_marcand, 'delay':delay,

        'bin_fpt':bin_fpt, 'fpt_distrib_2D':fpt_distrib_2D, 'fpt_number':fpt_number,

        'tbj_points':tbj_points, 'tbj_distrib':tbj_distrib,

        'dx_points':dx_points, 'dx_distrib':dx_distrib, 'dx_mean':dx_mean, 'dx_med':dx_med, 'dx_mp':dx_mp, 
        'dt_points':dt_points, 'dt_distrib':dt_distrib, 'dt_mean':dt_mean, 'dt_med':dt_med, 'dt_mp':dt_mp, 
        'vi_points':vi_points, 'vi_distrib':vi_distrib, 'vi_mean':vi_mean, 'vi_med':vi_med, 'vi_mp':vi_mp,
    }

    # # Types of data registered if needed
    # inspect_data_types(data_result)

    # Writing event
    writing_parquet(path, title, data_result)

    # Second cleaning
    for key in list(data_result.keys()):
        del data_result[key]
        if key in locals():
            del locals()[key]
    del data_result 
    gc.collect()

    # Done
    return None


# ================================================
# Part 3.2 : Multiprocessing functions
# ================================================


def choose_configuration(config: str):
    """
    Select the study configuration based on the given configuration identifier.

    """

    # Fixed parameters
    alphaf = 1
    alphao = 0
    alpha_choice_values = ["array"]

    # Configurations
    if config == "DATA":
        gap_values = np.arange(5, 35+5, 5)
        bpmin_values = np.array([0,2])
        mu_values = np.arange(1, 200+1, 2)
        theta_values = np.arange(1, 100+1, 2)
        nt = 10_000
        path = "mrc_data"
        
    elif config == "TEST":
        # gap_values = np.array([5, 35])
        gap_values = np.array([35])
        bpmin_values = np.array([0])
        # mu_values = np.array([1, 100, 200+1])
        mu_values = np.array([100])
        # theta_values = np.array([1, 50, 100+1])
        theta_values = np.array([50])
        nt = 10_000
        path = "mrc_test"
        print(os.getcwd())

    else:
        raise ValueError(f"Unknown configuration identifier: {config}")

    return alpha_choice_values, gap_values, bpmin_values, mu_values, theta_values, alphaf, alphao, nt, path


def process_function(params):
    """
    Defines one process
    """
    alpha_choice, gap, bpmin, mu, theta, alphaf, alphao, nt, path,  = params
    # logging.debug(f'Processing : s={s}, l={l}, bp_min={bp_min}, alpha_choice={alpha_choice}, k={k}, theta={theta}')
    sw_marcand(alpha_choice, gap, bpmin, alphaf, alphao, mu, theta, origin, nt, path)
    return None


def execute_in_parallel(config: str, execution_mode: str) -> None:
    """
    Launches all the process
    """
    # Inputs
    alpha_choice_values, bpmin_values, gap_values, mu_values, theta_values, alphaf, alphao, nt, path  = choose_configuration(config)
    
    #- Inputs
    params_list = [
        (alpha_choice, bp_min, gap, mu, theta, alphaf, alphao, nt, path,)
        for alpha_choice in alpha_choice_values
        for bp_min in bpmin_values
        for gap in gap_values
        for mu in mu_values
        for theta in theta_values
    ]
    
    #- Chunks
    chunk_size = len(params_list) // num_tasks
    start = task_id * chunk_size
    end = start + chunk_size if task_id < num_tasks - 1 else len(params_list)
    params_list_task = params_list[start:end]

    #- Environment
    # path_initial = "/marcand/outputs/"
    # folder_path = os.path.join(os.getcwd() + path_initial, f'{path}_{task_id}')
    # set_working_environment(folder_path)
    # print(os.getcwd())
    folder_name = f"{path}_{task_id}"
    set_working_environment(subfolder=folder_name)

    # Execution modes
    if execution_mode == 'PSMN' :
        num_processes = num_cores_used
        with ProcessPoolExecutor(max_workers=num_processes) as executor:
            futures = {executor.submit(process_function, params): params for params in params_list_task}
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    print(f"Process failed with exception: {e}")
        return None

    if execution_mode == 'PC' :
        num_processes = 4

        with ProcessPoolExecutor(max_workers=num_processes) as executor:
            futures = {executor.submit(process_function, params): params for params in params_list}
            for future in tqdm(as_completed(futures), total=len(futures), desc="Processing"):
                try:
                    future.result()
                except Exception as e:
                    print(f"Process failed with exception: {e}")
        return None
    

# ================================================
# Part 4 : Main
# ================================================

# 4.1 : Inputs



# 4.2 : Slurm parameters
num_cores_used = int(os.getenv('SLURM_CPUS_PER_TASK', '1'))
num_tasks = int(os.getenv('SLURM_NTASKS', '1'))
task_id = int(os.getenv('SLURM_PROCID', '0'))


# 4.3 : Main function
def main():
    print('\n#- Launched -#\n')
    start_time = time.time()
    initial_adress = Path.cwd()

    config = 'DATA'         # DATA / TEST
    exe = 'PC'              # PSMN / PC / SNAKEVIZ

    try:
        execute_in_parallel(config, exe)
    except Exception as e:
        print(f"Process failed: {e}")

    os.chdir(initial_adress)
    end_time = time.time()
    elapsed_time = end_time - start_time
    print(f'\n#- Finished in {int(elapsed_time // 60)}m at {initial_adress} -#\n')


# 4.4 : Main launch
if __name__ == '__main__':

    origin = 0

    main()


# ================================================
# .
# ================================================