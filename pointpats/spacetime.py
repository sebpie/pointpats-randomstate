"""
Methods for identifying space-time interaction in spatio-temporal event
data.
"""
__author__ = "Nicholas Malizia <nmalizia@asu.edu>", "Sergio J. Rey \
<srey@asu.edu>", "Philip Stephens <philip.stephens@asu.edu"

__all__ = ['SpaceTimeEvents', 'knox', 'mantel', 'jacquez', 'modified_knox']

import os
import libpysal as lps
import numpy as np
import scipy.stats as stats
from libpysal import cg
from datetime import date
from scipy.spatial import KDTree
from scipy.stats import poisson
from scipy.stats import hypergeom

class SpaceTimeEvents:
    """
    Method for reformatting event data stored in a shapefile for use in
    calculating metrics of spatio-temporal interaction.

    Parameters
    ----------
    path            : string
                      the path to the appropriate shapefile, including the
                      file name and extension
    time            : string
                      column header in the DBF file indicating the column
                      containing the time stamp.
    infer_timestamp : bool, optional
                      if the column containing the timestamp is formatted as
                      calendar dates, try to coerce them into Python datetime
                      objects (the default is False).

    Attributes
    ----------
    n               : int
                      number of events.
    x               : array
                      (n, 1), array of the x coordinates for the events.
    y               : array
                      (n, 1), array of the y coordinates for the events.
    t               : array
                      (n, 1), array of the temporal coordinates for the events.
    space           : array
                      (n, 2), array of the spatial coordinates (x,y) for the
                      events.
    time            : array
                      (n, 2), array of the temporal coordinates (t,1) for the
                      events, the second column is a vector of ones.

    Examples
    --------
    Read in the example shapefile data, ensuring to omit the file
    extension. In order to successfully create the event data the .dbf file
    associated with the shapefile should have a column of values that are a
    timestamp for the events. This timestamp may be a numerical value
    or a date. Date inference was added in version 1.6.

    >>> import libpysal as lps
    >>> path = lps.examples.get_path("burkitt.shp")
    >>> from pointpats import SpaceTimeEvents

    Create an instance of SpaceTimeEvents from a shapefile, where the
    temporal information is stored in a column named "T".

    >>> events = SpaceTimeEvents(path,'T')

    See how many events are in the instance.

    >>> events.n
    188

    Check the spatial coordinates of the first event.

    >>> events.space[0]
    array([300., 302.])

    Check the time of the first event.

    >>> events.t[0]
    array([413.])

    Calculate the time difference between the first two events.

    >>> events.t[1] - events.t[0]
    array([59.])

    New, in 1.6, date support:
    Now, create an instance of SpaceTimeEvents from a shapefile, where the
    temporal information is stored in a column named "DATE".

    >>> events = SpaceTimeEvents(path,'DATE')

    See how many events are in the instance.

    >>> events.n
    188

    Check the spatial coordinates of the first event.

    >>> events.space[0]
    array([300., 302.])

    Check the time of the first event. Note that this value is equivalent to
    413 days after January 1, 1900.

    >>> events.t[0][0]
    datetime.date(1901, 2, 16)

    Calculate the time difference between the first two events.

    >>> (events.t[1][0] - events.t[0][0]).days
    59
    """
    def __init__(self, path, time_col, infer_timestamp=False):
        shp = lps.io.open(path)
        head, tail = os.path.split(path)
        dbf_tail = tail.split(".")[0]+".dbf"
        dbf = lps.io.open(lps.examples.get_path(dbf_tail))

        # extract the spatial coordinates from the shapefile
        x = [coords[0] for coords in shp]
        y = [coords[1] for coords in shp]

        self.n = n = len(shp)
        x = np.array(x)
        y = np.array(y)
        self.x = np.reshape(x, (n, 1))
        self.y = np.reshape(y, (n, 1))
        self.space = np.hstack((self.x, self.y))

        # extract the temporal information from the database
        if infer_timestamp:
            col = dbf.by_col(time_col)
            if isinstance(col[0], date):
                day1 = min(col)
                col = [(d - day1).days for d in col]
                t = np.array(col)
            else:
                print("Unable to parse your time column as Python datetime \
                      objects, proceeding as integers.")
                t = np.array(col)
        else:
            t = np.array(dbf.by_col(time_col))
        line = np.ones((n, 1))
        self.t = np.reshape(t, (n, 1))
        self.time = np.hstack((self.t, line))

        # close open objects
        dbf.close()
        shp.close()


def knox(s_coords, t_coords, delta, tau, permutations=99, debug=False):
    """
    Knox test for spatio-temporal interaction. :cite:`Knox:1964`

    Parameters
    ----------
    s_coords        : array
                      (n, 2), spatial coordinates.
    t_coords        : array
                      (n, 1), temporal coordinates.
    delta           : float
                      threshold for proximity in space.
    tau             : float
                      threshold for proximity in time.
    permutations    : int, optional
                      the number of permutations used to establish pseudo-
                      significance (the default is 99).
    debug           : bool, optional
                      if true, debugging information is printed (the default is
                      False).

    Returns
    -------
    knox_result     : dictionary
                      contains the statistic (stat) for the test and the
                      associated p-value (pvalue).
    stat            : float
                      value of the knox test for the dataset.
    pvalue          : float
                      pseudo p-value associated with the statistic.
    counts          : int
                      count of space time neighbors.

    Examples
    --------
    >>> import numpy as np
    >>> import libpysal as lps
    >>> from pointpats import SpaceTimeEvents, knox

    Read in the example data and create an instance of SpaceTimeEvents.

    >>> path = lps.examples.get_path("burkitt.shp")
    >>> events = SpaceTimeEvents(path,'T')

    Set the random seed generator. This is used by the permutation based
    inference to replicate the pseudo-significance of our example results -
    the end-user will normally omit this step.

    >>> np.random.seed(100)

    Run the Knox test with distance and time thresholds of 20 and 5,
    respectively. This counts the events that are closer than 20 units in
    space, and 5 units in time.

    >>> result = knox(events.space, events.t, delta=20, tau=5, permutations=99)

    Next, we examine the results. First, we call the statistic from the
    results dictionary. This reports that there are 13 events close
    in both space and time, according to our threshold definitions.

    >>> result['stat'] == 13
    True

    Next, we look at the pseudo-significance of this value, calculated by
    permuting the timestamps and rerunning the statistics. In this case,
    the results indicate there is likely no space-time interaction between
    the events.

    >>> print("%2.2f"%result['pvalue'])
    0.17
    """

    # Do a kdtree on space first as the number of ties (identical points) is
    # likely to be lower for space than time.

    kd_s = cg.KDTree(s_coords)
    neigh_s = kd_s.query_pairs(delta)
    tau2 = tau * tau
    ids = np.array(list(neigh_s))

    # For the neighboring pairs in space, determine which are also time
    # neighbors

    d_t = (t_coords[ids[:, 0]] - t_coords[ids[:, 1]]) ** 2
    n_st = sum(d_t <= tau2)

    knox_result = {'stat': n_st[0]}

    if permutations:
        joint = np.zeros((permutations, 1), int)
        for p in range(permutations):
            np.random.shuffle(t_coords)
            d_t = (t_coords[ids[:, 0]] - t_coords[ids[:, 1]]) ** 2
            joint[p] = np.sum(d_t <= tau2)

        larger = sum(joint >= n_st[0])
        if (permutations - larger) < larger:
            larger = permutations - larger
        p_sim = (larger + 1.) / (permutations + 1.)
        knox_result['pvalue'] = p_sim
    return knox_result


def mantel(s_coords, t_coords, permutations=99, scon=1.0, spow=-1.0, tcon=1.0, tpow=-1.0):
    """
    Standardized Mantel test for spatio-temporal interaction. :cite:`Mantel:1967`

    Parameters
    ----------
    s_coords        : array
                      (n, 2), spatial coordinates.
    t_coords        : array
                      (n, 1), temporal coordinates.
    permutations    : int, optional
                      the number of permutations used to establish pseudo-
                      significance (the default is 99).
    scon            : float, optional
                      constant added to spatial distances (the default is 1.0).
    spow            : float, optional
                      value for power transformation for spatial distances
                      (the default is -1.0).
    tcon            : float, optional
                      constant added to temporal distances (the default is 1.0).
    tpow            : float, optional
                      value for power transformation for temporal distances
                      (the default is -1.0).

    Returns
    -------
    mantel_result   : dictionary
                      contains the statistic (stat) for the test and the
                      associated p-value (pvalue).
    stat            : float
                      value of the knox test for the dataset.
    pvalue          : float
                      pseudo p-value associated with the statistic.

    Examples
    --------
    >>> import numpy as np
    >>> import libpysal as lps
    >>> from pointpats import SpaceTimeEvents, mantel

    Read in the example data and create an instance of SpaceTimeEvents.

    >>> path = lps.examples.get_path("burkitt.shp")
    >>> events = SpaceTimeEvents(path,'T')

    Set the random seed generator. This is used by the permutation based
    inference to replicate the pseudo-significance of our example results -
    the end-user will normally omit this step.

    >>> np.random.seed(100)

    The standardized Mantel test is a measure of matrix correlation between
    the spatial and temporal distance matrices of the event dataset. The
    following example runs the standardized Mantel test without a constant
    or transformation; however, as recommended by :cite:`Mantel:1967`, these
    should be added by the user. This can be done by adjusting the constant
    and power parameters.

    >>> result = mantel(events.space, events.t, 99, scon=1.0, spow=-1.0, tcon=1.0, tpow=-1.0)

    Next, we examine the result of the test.

    >>> print("%6.6f"%result['stat'])
    0.048368

    Finally, we look at the pseudo-significance of this value, calculated by
    permuting the timestamps and rerunning the statistic for each of the 99
    permutations. According to these parameters, the results indicate
    space-time interaction between the events.

    >>> print("%2.2f"%result['pvalue'])
    0.01

    """

    t = t_coords
    s = s_coords
    n = len(t)

    # calculate the spatial and temporal distance matrices for the events
    distmat = cg.distance_matrix(s)
    timemat = cg.distance_matrix(t)

    # calculate the transformed standardized statistic
    timevec = (timemat[np.tril_indices(timemat.shape[0], k = -1)] + tcon) ** tpow
    distvec = (distmat[np.tril_indices(distmat.shape[0], k = -1)] + scon) ** spow
    stat = stats.pearsonr(timevec, distvec)[0].sum()

    # return the results (if no inference)
    if not permutations:
        return stat

    # loop for generating a random distribution to assess significance
    dist = []
    for i in range(permutations):
        trand = _shuffle_matrix(timemat, np.arange(n))
        timevec = (trand[np.tril_indices(trand.shape[0], k = -1)] + tcon) ** tpow
        m = stats.pearsonr(timevec, distvec)[0].sum()
        dist.append(m)

    ## establish the pseudo significance of the observed statistic
    distribution = np.array(dist)
    greater = np.ma.masked_greater_equal(distribution, stat)
    count = np.ma.count_masked(greater)
    pvalue = (count + 1.0) / (permutations + 1.0)

    # report the results
    mantel_result = {'stat': stat, 'pvalue': pvalue}
    return mantel_result


def jacquez(s_coords, t_coords, k, permutations=99):
    """
    Jacquez k nearest neighbors test for spatio-temporal interaction.
    :cite:`Jacquez:1996`

    Parameters
    ----------
    s_coords        : array
                      (n, 2), spatial coordinates.
    t_coords        : array
                      (n, 1), temporal coordinates.
    k               : int
                      the number of nearest neighbors to be searched.
    permutations    : int, optional
                      the number of permutations used to establish pseudo-
                      significance (the default is 99).

    Returns
    -------
    jacquez_result  : dictionary
                      contains the statistic (stat) for the test and the
                      associated p-value (pvalue).
    stat            : float
                      value of the Jacquez k nearest neighbors test for the
                      dataset.
    pvalue          : float
                      p-value associated with the statistic (normally
                      distributed with k-1 df).

    Examples
    --------
    >>> import numpy as np
    >>> import libpysal as lps
    >>> from pointpats import SpaceTimeEvents, jacquez

    Read in the example data and create an instance of SpaceTimeEvents.

    >>> path = lps.examples.get_path("burkitt.shp")
    >>> events = SpaceTimeEvents(path,'T')

    The Jacquez test counts the number of events that are k nearest
    neighbors in both time and space. The following runs the Jacquez test
    on the example data and reports the resulting statistic. In this case,
    there are 13 instances where events are nearest neighbors in both space
    and time.
    # turning off as kdtree changes from scipy < 0.12 return 13

    >>> np.random.seed(100)
    >>> result = jacquez(events.space, events.t ,k=3,permutations=99)
    >>> print(result['stat'])
    13

    The significance of this can be assessed by calling the p-
    value from the results dictionary, as shown below. Again, no
    space-time interaction is observed.

    >>> result['pvalue'] < 0.01
    False

    """
    time = t_coords
    space = s_coords
    n = len(time)

    # calculate the nearest neighbors in space and time separately
    knnt = lps.weights.KNN.from_array(time, k)
    knns = lps.weights.KNN.from_array(space, k)

    nnt = knnt.neighbors
    nns = knns.neighbors
    knn_sum = 0

    # determine which events are nearest neighbors in both space and time
    for i in range(n):
        t_neighbors = nnt[i]
        s_neighbors = nns[i]
        check = set(t_neighbors)
        inter = check.intersection(s_neighbors)
        count = len(inter)
        knn_sum += count

    stat = knn_sum

    # return the results (if no inference)
    if not permutations:
        return stat

    # loop for generating a random distribution to assess significance
    dist = []
    for p in range(permutations):
        j = 0
        trand = np.random.permutation(time)
        knnt = lps.weights.KNN.from_array(trand, k)
        nnt = knnt.neighbors
        for i in range(n):
            t_neighbors = nnt[i]
            s_neighbors = nns[i]
            check = set(t_neighbors)
            inter = check.intersection(s_neighbors)
            count = len(inter)
            j += count

        dist.append(j)

    # establish the pseudo significance of the observed statistic
    distribution = np.array(dist)
    greater = np.ma.masked_greater_equal(distribution, stat)
    count = np.ma.count_masked(greater)
    pvalue = (count + 1.0) / (permutations + 1.0)

    # report the results
    jacquez_result = {'stat': stat, 'pvalue': pvalue}
    return jacquez_result


def modified_knox(s_coords, t_coords, delta, tau, permutations=99):
    """
    Baker's modified Knox test for spatio-temporal interaction.
    :cite:`Baker:2004`

    Parameters
    ----------
    s_coords        : array
                      (n, 2), spatial coordinates.
    t_coords        : array
                      (n, 1), temporal coordinates.
    delta           : float
                      threshold for proximity in space.
    tau             : float
                      threshold for proximity in time.
    permutations    : int, optional
                      the number of permutations used to establish pseudo-
                      significance (the default is 99).

    Returns
    -------
    modknox_result  : dictionary
                      contains the statistic (stat) for the test and the
                      associated p-value (pvalue).
    stat            : float
                      value of the modified knox test for the dataset.
    pvalue          : float
                      pseudo p-value associated with the statistic.

    Examples
    --------
    >>> import numpy as np
    >>> import libpysal as lps
    >>> from pointpats import SpaceTimeEvents, modified_knox

    Read in the example data and create an instance of SpaceTimeEvents.

    >>> path = lps.examples.get_path("burkitt.shp")
    >>> events = SpaceTimeEvents(path, 'T')

    Set the random seed generator. This is used by the permutation based
    inference to replicate the pseudo-significance of our example results -
    the end-user will normally omit this step.

    >>> np.random.seed(100)

    Run the modified Knox test with distance and time thresholds of 20 and 5,
    respectively. This counts the events that are closer than 20 units in
    space, and 5 units in time.

    >>> result = modified_knox(events.space, events.t, delta=20, tau=5, permutations=99)

    Next, we examine the results. First, we call the statistic from the
    results dictionary. This reports the difference between the observed
    and expected Knox statistic.

    >>> print("%2.8f" % result['stat'])
    2.81016043

    Next, we look at the pseudo-significance of this value, calculated by
    permuting the timestamps and rerunning the statistics. In this case,
    the results indicate there is likely no space-time interaction.

    >>> print("%2.2f" % result['pvalue'])
    0.11

    """
    s = s_coords
    t = t_coords
    n = len(t)

    # calculate the spatial and temporal distance matrices for the events
    sdistmat = cg.distance_matrix(s)
    tdistmat = cg.distance_matrix(t)

    # identify events within thresholds
    spacmat = np.ones((n, n))
    spacbin = sdistmat <= delta
    spacmat = spacmat * spacbin
    timemat = np.ones((n, n))
    timebin = tdistmat <= tau
    timemat = timemat * timebin

    # calculate the observed (original) statistic
    knoxmat = timemat * spacmat
    obsstat = (knoxmat.sum() - n)

    # calculate the expectated value
    ssumvec = np.reshape((spacbin.sum(axis=0) - 1), (n, 1))
    tsumvec = np.reshape((timebin.sum(axis=0) - 1), (n, 1))
    expstat = (ssumvec * tsumvec).sum()

    # calculate the modified stat
    stat = (obsstat - (expstat / (n - 1.0))) / 2.0

    # return results (if no inference)
    if not permutations:
        return stat
    distribution = []

    # loop for generating a random distribution to assess significance
    for p in range(permutations):
        rtdistmat = _shuffle_matrix(tdistmat, list(range(n)))
        timemat = np.ones((n, n))
        timebin = rtdistmat <= tau
        timemat = timemat * timebin

        # calculate the observed knox again
        knoxmat = timemat * spacmat
        obsstat = (knoxmat.sum() - n)

        # calculate the expectated value again
        ssumvec = np.reshape((spacbin.sum(axis=0) - 1), (n, 1))
        tsumvec = np.reshape((timebin.sum(axis=0) - 1), (n, 1))
        expstat = (ssumvec * tsumvec).sum()

        # calculate the modified stat
        tempstat = (obsstat - (expstat / (n - 1.0))) / 2.0
        distribution.append(tempstat)

    # establish the pseudo significance of the observed statistic
    distribution = np.array(distribution)
    greater = np.ma.masked_greater_equal(distribution, stat)
    count = np.ma.count_masked(greater)
    pvalue = (count + 1.0) / (permutations + 1.0)

    # return results
    modknox_result = {'stat': stat, 'pvalue': pvalue}
    return modknox_result

def _shuffle_matrix(X, ids):
    """
    Random permutation of rows and columns of a matrix

    Parameters
    ----------
    X   : array
          (k, k), array to be permuted.
    ids : array
          range (k, ).

    Returns
    -------
        : array
          (k, k) with rows and columns randomly shuffled.
    """
    np.random.shuffle(ids)
    return X[ids, :][:, ids]


def _knox(s_coords, t_coords, delta, tau, permutations=99, keep=False):
    """
    Parameters
    ==========

    s_coords: array-like
      spatial coordinates
    t_coords: array-like
      temporal coordinates
    delta: float
      distance threshold
    tau: float
      temporal threshold
    permutations: int
      number of permutations
    keep: bool
      return values from permutations (default False)


    Returns
    =======

    summary table observed
    summary table h0

    ns
    nt
    nst
    n
    p-value
    """

    n = s_coords.shape[0]


    stree = KDTree(s_coords)
    ttree = KDTree(t_coords)
    sneighbors = stree.query_ball_tree(stree, r=delta)
    sneighbors = [set(neighbors).difference([i]) for i,neighbors in enumerate(sneighbors)]
    tneighbors = ttree.query_ball_tree(ttree, r=tau)
    tneighbors = [set(neighbors).difference([i]) for i,neighbors in enumerate(tneighbors)]

    # number of spatial neighbor pairs
    ns = np.array([len(neighbors) for neighbors in sneighbors]) # by i

    NS = ns.sum() / 2 # total

    # number of temporal neigbor pairs
    nt = np.array([len(neighbors) for neighbors in tneighbors])
    NT = nt.sum() / 2


    # s-t neighbors (list of lists)
    stneighbors = [sneighbors_i.intersection(tneighbors_i) for sneighbors_i, tneighbors_i in zip(sneighbors, tneighbors)]



    # number of spatio-temporal neigbor pairs
    nst = np.array([len(neighbors) for neighbors in stneighbors])
    NST = nst.sum()/2

    all_pairs = []
    pairs = {}
    for i, neigh in enumerate(stneighbors):
        if len(neigh) > 0:
            all_pairs.extend([sorted((i,j)) for j in neigh])
    st_pairs = set([tuple(l) for l in all_pairs])



    # ENST: expected number of spatio-temporal neighbors under HO
    pairs = n * (n-1) / 2
    ENST = NS * NT / pairs


    # observed table
    observed = np.zeros((2,2))

    NS_ = NS - NST   # spatial only
    NT_ = NT - NST   # temporal only

    observed[0,0] = NST
    observed[0,1] = NS_
    observed[1,0] = NT_
    observed[1,1] = pairs - NST - NS_ - NT_

    # expected table

    expected = np.zeros((2,2))
    expected[0,0]  = NS * NT / pairs
    expected[0,1] = NS - expected[0,0]
    expected[1,0] = NT - expected[0,0]
    expected[1,1] = pairs - expected.sum()

    p_value_poisson = 1 - poisson.cdf(NST, expected[0,0])

    results = {}
    results['ns'] = ns.sum() / 2
    results['nt'] = nt.sum() / 2
    results['nst'] = nst.sum() / 2
    results['pairs'] = pairs
    results['expected'] = expected
    results['observed'] = observed
    results['p_value_poisson'] = p_value_poisson
    results['st_pairs'] = st_pairs
    results['sneighbors'] = sneighbors
    results['tneighbors'] = tneighbors


    if permutations > 0:
        exceedence = 0
        n = len(sneighbors)
        ids = np.arange(n)
        if keep:
            ST = np.zeros(permutations)

        for perm in range(permutations):
            st = 0
            rids = np.random.permutation(ids)
            for i in range(n):
                ri = rids[i]
                tni = tneighbors[ri]
                rjs = [rids[j] for j in sneighbors[i]]
                sti = [j for j in rjs if j in tni]
                st += len(sti)
            st /= 2
            if st >= results['nst']:
                exceedence += 1
            if keep:
                ST[perm] = st
        results['p_value_sim'] = (exceedence + 1) / (permutations + 1)
        results['exceedence'] = exceedence
        if keep:
            results['st_perm'] = ST

    return results


class Knox:
    """
    Global Knox statistic for space-time interactions

    Parameters
    ----------

    s_coords: array-like
      spatial coordinates of point events

    t_coords: array-like
      temporal coordinates of point events (floats or ints, not dateTime)

    delta: float
      spatial threshold defining distance below which pairs are spatial
      neighbors

    tau: float
      temporal threshold defining distance below which pairs are temporal
      neighbors

    permutations: int
      number of random permutations for inference

    keep: bool
      whether to store realized values of the statistic under permutations



    Attributes
    ----------

    s_coords: array-like
      spatial coordinates of point events

    t_coords: array-like
      temporal coordinates of point events (floats or ints, not dateTime)

    delta: float
      spatial threshold defining distance below which pairs are spatial
      neighbors

    tau: float
      temporal threshold defining distance below which pairs are temporal
      neighbors

    permutations: int
      number of random permutations for inference

    keep: bool
      whether to store realized values of the statistic under permutations

    nst: int
      number of space-time pairs

    p_poisson: float
      Analytical p-value under Poisson assumption

    p_sim: float
      Pseudo p-value based on random permutations

    expected: array
      Two-by-two array with expected counts under the null of no space-time
      interactions. [[NST, NS_], [NT_, N__]] where NST is the expected number
      of space-time pairs, NS_ is the expected number of spatial (but not also
      temporal) pairs, NT_ is the number of expected temporal (but not also
      spatial pairs), N__ is the number of pairs that are neighor spatial or
      temporal neighbors.

    observed: array
      Same structure as expected with the observed pair classifications

    sim: array
      Global statistics from permutations (if keep=True)


    """
    def __init__(self, s_coords, t_coords, delta, tau, permutations=99,
                 keep=False):
        self.s_coords = s_coords
        self.t_coords = t_coords
        self.delta = delta
        self.tau = tau
        self.permutations = permutations
        self.keep = keep
        results = _knox(s_coords, t_coords, delta, tau, permutations, keep)
        self.nst = int(results['nst'])
        if permutations>0:
            self.p_sim = results['p_value_sim']
            if keep:
                self.sim = results['st_perm']

        self.p_poisson = results['p_value_poisson']
        self.observed = results['observed']
        self.expected = results['expected']

    @property
    def _statistic(self):
        return self.nst


def _knox_local(s_coords, t_coords, delta, tau, permutations=99, keep=False):
    res = _knox(s_coords, t_coords, delta, tau, permutations=99)
    sneighbors = { i:tuple(ns) for i, ns in enumerate(res['sneighbors']) }
    tneighbors = { i:tuple(nt) for i, nt in enumerate(res['tneighbors']) }

    n= len(s_coords)
    ids = np.arange(n)
    res['nsti'] = np.zeros(n)  # number of observed st_pairs for observation i
    res['nsi'] = [len(r) for r in res['sneighbors']]
    res['nti'] = [len(r) for r in res['sneighbors']]
    for pair in res['st_pairs']:
        i, j = pair
        res['nsti'][i] += 1
        res['nsti'][j] += 1

    nsti = res['nsti']
    nsi = res['nsi']
    nti = res['nti']
    if permutations > 0:
        exceedence = np.zeros(n)
        if keep:
            STI = np.zeros((n,permutations))
        for perm in range(permutations):
            rids = np.random.permutation(ids)
            for i in range(n):
                # set observed value of focal unit i
                # swap with value assigned to rids[i]
                j = np.where(rids==i)
                a = rids[i]
                rids[j] = a
                rids[i] = i

                # calculate local stat
                rjs = [rids[j] for j in sneighbors[i]]
                tni = tneighbors[i]
                sti = [j for j in rjs if j in tni]
                count = len(sti)
                if count >= res['nsti'][i]:
                    exceedence[i] += 1
                if keep:
                    STI[i, perm] = count

                # reset value of focal unit i to random value
                rids[j] = i
                rids[i] = a
        if keep:
            res['sti_perm'] = STI
        res['exceedence_pvalue'] = (exceedence + 1) / (permutations + 1)
        res['exceedences'] = exceedence

    # analytical inference
    ntjis = [len(r) for r in res['tneighbors']]
    n1 = n - 1
    hg_pvalues = [ 1-hypergeom.cdf(nsti[i]-1, n1, ntjis, nsi[i]).mean() for i in
                  range(n) ]
    res['hg_pvalues'] = np.array(hg_pvalues)

    return res


class Knox_Local:
    """
    Local Knox statistics for space-time interactions

    Parameters
    ----------

    s_coords: array-like
      spatial coordinates of point events

    t_coords: array-like
      temporal coordinates of point events (floats or ints, not dateTime)

    delta: float
      spatial threshold defining distance below which pairs are spatial
      neighbors

    tau: float
      temporal threshold defining distance below which pairs are temporal
      neighbors

    permutations: int
      number of random permutations for inference

    keep: bool
      whether to store realized values of the statistic under permutations

    conditional: bool
      whether to include conditional permutation inference



    Attributes
    ----------

    s_coords: array-like
      spatial coordinates of point events

    t_coords: array-like
      temporal coordinates of point events (floats or ints, not dateTime)

    delta: float
      spatial threshold defining distance below which pairs are spatial
      neighbors

    tau: float
      temporal threshold defining distance below which pairs are temporal
      neighbors

    permutations: int
      number of random permutations for inference

    keep: bool
      whether to store realized values of the statistic under permutations

    nst: int
      number of space-time pairs (global)

    p_poisson: float
      Analytical p-value under Poisson assumption (global)

    p_sim: float
      Pseudo p-value based on random permutations (global)

    expected: array
      Two-by-two array with expected counts under the null of no space-time
      interactions. [[NST, NS_], [NT_, N__]] where NST is the expected number
      of space-time pairs, NS_ is the expected number of spatial (but not also
      temporal) pairs, NT_ is the number of expected temporal (but not also
      spatial pairs), N__ is the number of pairs that are neighor spatial or
      temporal neighbors. (global)

    observed: array
      Same structure as expected with the observed pair classifications (global)

    sim: array
      Global statistics from permutations (if keep=True and keep=True) (global)

    p_sims: array
      Local psuedo p-values from conditional permutations (if permutations>0)

    sims: array
      Local statistics from conditional permutations (if keep=True)

    nsti: array
      Local statistics

    p_hypergeom: array
      Analyitcal p-values based on hypergeometric distribution


    """
    def __init__(self, s_coords, t_coords, delta, tau, permutations=99,
                 keep=False):
        self.s_coords = s_coords
        self.t_coords = t_coords
        self.delta = delta
        self.tau = tau
        self.permutations = permutations
        self.keep = keep
        results = _knox_local(s_coords, t_coords, delta, tau, permutations, keep)
        self.nst = int(results['nst'])
        if permutations>0:
            self.p_sim = results['p_value_sim']
            if keep:
                self.sim = results['st_perm']

        self.p_poisson = results['p_value_poisson']
        self.observed = results['observed']
        self.expected = results['expected']
        self.p_hypergeom = results['hg_pvalues']
        if permutations > 0:
            self.p_sims = results['exceedence_pvalue']
            if keep:
                self.sims = results['sti_perm']
        self.nsti = results['nsti']

    @property
    def _statistic(self):
        return self.nsti


