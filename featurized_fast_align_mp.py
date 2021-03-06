__author__ = 'arenduchintala'

from optparse import OptionParser
from math import exp, log
from scipy.optimize import minimize
import numpy as np

import utils
import copy
import pdb
from math import floor
import multiprocessing
from multiprocessing import Pool
import traceback
import sharedmem
import random

np.seterr(all='raise')

from const import NULL, BOUNDARY_START, BOUNDARY_END, IBM_MODEL_1, HMM_MODEL, E_TYPE, T_TYPE, EPS, Po
from cyth.cyth_common import populate_trellis, populate_features, write_alignments, write_alignments_col, \
    write_alignments_col_tok, write_probs, write_weights, initialize_theta, get_wa_features_fired, \
    load_dictionary_features, load_corpus_file


global cache_normalizing_decision, features_to_events, events_to_features, normalizing_decision_map, num_toks
global trellis, max_jump_width, number_of_events, EPS, snippet, max_beam_width, rc
global source, target, data_likelihood, event_grad, feature_index, event_index
global events_per_trellis, event_to_event_index, has_pos, event_counts, du, itercount, N
global diagonal_tension, emp_feat, sum_likelihood, dictionary_features
dictionary_features = {}
has_pos = False
event_grad = {}
data_likelihood = 0.0
snippet = ''
EPS = 1e-5
rc = 0.25

max_jump_width = 10
max_beam_width = 20  # creates a span of +/- span centered around current token
trellis = []
cache_normalizing_decision = {}

fractional_counts = {}
number_of_events = 0
events_to_features = {}
features_to_events = {}
feature_index = {}
feature_counts = {}
du = []
event_index = []
event_to_event_index = {}
event_counts = {}

normalizing_decision_map = {}
itercount = 0


def populate_events_per_trellis():
    global event_index, trellis, events_per_trellis
    events_per_trellis = []
    for obs_id, obs in enumerate(trellis):
        events_observed = []
        obs = trellis[obs_id]
        src = source[obs_id]
        tar = target[obs_id]
        for k in range(1, len(obs)):  # the words are numbered from 1 to n, 0 is special start character
            for v in obs[k]:  # [1]:
                for u in obs[k - 1]:  # [1]:
                    tk, aj = v
                    tk_1, aj_1 = u
                    t_tok = tar[tk]
                    s_tok = src[aj] if aj is not NULL else NULL

                    ei = event_to_event_index[(E_TYPE, t_tok, s_tok)]
                    events_observed.append(ei)
        events_per_trellis.append(list(set(events_observed)))


def compute_z(i, m, n, dt):
    split = floor(i) * n / m
    flr = floor(split)
    ceil = flr + 1
    ratio = exp(-dt / n)
    num_top = n - flr
    ezt = 0
    ezb = 0
    if num_top != 0.0:
        ezt = unnormalized_prob(i, ceil, m, n, dt) * (1.0 - np.power(ratio, num_top)) / (1.0 - ratio)
    if flr != 0.0:
        ezb = unnormalized_prob(i, flr, m, n, dt) * (1.0 - np.power(ratio, flr)) / (1.0 - ratio)
    return ezb + ezt


def arithmetico_geo_series(a1, g1, r, d, n):
    gnp1 = g1 * np.power(r, n)
    an = d * (n - 1) + a1
    x1 = a1 * g1
    g2 = g1 * r
    rm1 = r - 1
    return (an * gnp1 - x1) / rm1 - d * (gnp1 - g2) / (rm1 * rm1)


def unnormalized_prob(i, j, m, n, dt):
    return exp(h(i, j, m, n) * dt)


def compute_d_log_z(i, m, n, dt):
    z = compute_z(i, n, m, dt)
    split = float(i) * n / m
    flr = floor(split)
    ceil = flr + 1
    ratio = exp(-dt / n)
    d = -1.0 / n
    num_top = n - flr
    pct = 0.0
    pcb = 0.0
    if num_top != 0:
        pct = arithmetico_geo_series(h(i, ceil, m, n), unnormalized_prob(i, ceil, m, n, dt), ratio, d,
                                     num_top)

    if flr != 0:
        pcb = arithmetico_geo_series(h(i, flr, m, n), unnormalized_prob(i, flr, m, n, dt), ratio, d, flr)
    return (pcb + pct) / z


def h(i, j, m, n):
    return - abs((float(i) / float(m)) - (float(j) / float(n)))


def get_decision_given_context(theta, type, decision, context):
    global normalizing_decision_map, cache_normalizing_decision, feature_index, dictionary_features
    fired_features = get_wa_features_fired(dictionary_features=dictionary_features, type=type, context=context,
                                           decision=decision)

    theta_dot_features = sum([theta[feature_index[f]] * f_wt for f_wt, f in fired_features])

    if (type, context) in cache_normalizing_decision:
        theta_dot_normalizing_features = cache_normalizing_decision[type, context]
    else:
        normalizing_decisions = normalizing_decision_map[type, context]
        theta_dot_normalizing_features = 0
        for d in normalizing_decisions:
            d_features = get_wa_features_fired(dictionary_features=dictionary_features, type=type, context=context,
                                               decision=d)
            theta_dot_normalizing_features += exp(sum([theta[feature_index[f]] * f_wt for f_wt, f in d_features]))

        theta_dot_normalizing_features = log(theta_dot_normalizing_features)
        cache_normalizing_decision[type, context] = theta_dot_normalizing_features
    log_prob = round(theta_dot_features - theta_dot_normalizing_features, 10)
    if log_prob > 0.0:
        # print "log_prob = ", log_prob, type, decision, context
        # pdb.set_trace()
        if options.algorithm == 'LBFGS':
            raise Exception
        else:
            log_prob = 0.0  # TODO figure out why in the EM algorithm this error happens?
    return log_prob


def get_model1_forward(theta, obs_id, fc=None, ef=None):
    global source, target, trellis, diagonal_tension
    obs = trellis[obs_id]
    m = len(obs)
    max_bt = [-1] * len(obs)
    p_st = 0.0
    for t_idx in obs:
        t_tok = target[obs_id][t_idx]
        sum_e = float('-inf')
        sum_pei = float('-inf')
        max_e = float('-inf')
        max_s_idx = None
        sum_sj = float('-inf')
        sum_q = float('-inf')
        for _, s_idx in obs[t_idx]:
            n = len(obs[t_idx])
            s_tok = source[obs_id][s_idx] if s_idx is not NULL else NULL
            e = get_decision_given_context(theta, E_TYPE, decision=t_tok, context=s_tok)
            sum_e = utils.logadd(sum_e, e)

            if t_tok == BOUNDARY_START or t_tok == BOUNDARY_END:
                q = 0.0
            elif s_tok == NULL:
                q = np.log(Po)
            else:
                # q = get_fast_align_transition(theta, t_idx, s_idx, m - 2, n - 1)
                az = compute_z(t_idx, m - 2, n - 1, diagonal_tension) / (1 - Po)
                q = np.log(unnormalized_prob(t_idx, s_idx, m - 2, n - 1, diagonal_tension) / az)

            sum_pei = utils.logadd(sum_pei, q + e)
            sum_sj = utils.logadd(sum_sj, e + q)
            sum_q = utils.logadd(sum_q, q)

            if e > max_e:
                max_e = e
                max_s_idx = s_idx
        max_bt[t_idx] = (t_idx, max_s_idx)
        p_st += sum_sj

        if p_st == float('inf'):
            pdb.set_trace()
        # update fractional counts
        if fc is not None:
            for _, s_idx in obs[t_idx]:
                n = len(obs[t_idx])
                s_tok = source[obs_id][s_idx] if s_idx is not NULL else NULL
                e = get_decision_given_context(theta, E_TYPE, decision=t_tok, context=s_tok)

                if t_tok == BOUNDARY_START or t_tok == BOUNDARY_END:
                    q = 0.0
                    hijmn = 0.0
                elif s_tok == NULL:
                    q = np.log(Po)
                    hijmn = 0.0
                else:
                    az = compute_z(t_idx, m - 2, n - 1, diagonal_tension) / (1 - Po)
                    q = np.log(unnormalized_prob(t_idx, s_idx, m - 2, n - 1, diagonal_tension) / az)
                    hijmn = h(t_idx, s_idx, m - 2, n - 1)

                p_ai = e + q - sum_pei  # TODO: times h(j',i,m,n)
                # p_q = q - sum_q
                event = (E_TYPE, t_tok, s_tok)
                fc[event] = utils.logadd(p_ai, fc.get(event, float('-inf')))
                ef += (exp(p_ai) * hijmn)

    return max_bt[:-1], p_st, fc, ef


def reset_fractional_counts():
    global fractional_counts, cache_normalizing_decision, number_of_events
    fractional_counts = {}  # dict((k, float('-inf')) for k in conditional_arc_index)
    cache_normalizing_decision = {}
    number_of_events = 0


def batch_likelihood(theta, batch):
    dl = 0.0
    batch_emp_feat = 0.0
    batch_fc = {}
    for idx in batch:
        max_bt, S, batch_fc, batch_emp_feat = get_model1_forward(theta, idx, batch_fc, batch_emp_feat)
        dl += S
    return dl, batch_fc, batch_emp_feat


def batch_accumilate_likelihood(result):
    global data_likelihood, fractional_counts, emp_feat
    data_likelihood += result[0]
    fc = result[1]
    emp_feat += result[2]
    for k in fc:
        fractional_counts[k] = utils.logadd(fc[k], fractional_counts.get(k, float('-inf')))


def get_likelihood(theta):
    assert isinstance(theta, np.ndarray)
    assert len(theta) == len(feature_index)
    global trellis, data_likelihood, rc, itercount, N, emp_feat
    reset_fractional_counts()
    data_likelihood = 0.0
    emp_feat = 0.0
    cpu_count = multiprocessing.cpu_count()
    pool = Pool(processes=cpu_count)  # uses all available CPUs
    full = range(0, len(trellis))
    batches = np.array_split(full, cpu_count)
    for batch in batches:
        pool.apply_async(batch_likelihood, args=(theta, batch), callback=batch_accumilate_likelihood)
    pool.close()
    pool.join()
    reg = np.sum(theta ** 2)
    ll = (data_likelihood - (rc * reg))
    e1 = get_decision_given_context(theta, E_TYPE, decision='.', context=NULL)
    e2 = get_decision_given_context(theta, E_TYPE, decision='.', context='.')
    print 'log likelihood:', ll, 'p(.|NULL)', e1, 'p(.|.)', e2, 'lf', diagonal_tension
    print 'emp_feat_norm', emp_feat / num_toks

    return -ll


def batch_likelihood_with_expected_counts(theta, batch_of_fc):
    global event_index
    batch_sum_likelihood = 0.0
    for idx in batch_of_fc:
        event = event_index[idx]
        (t, d, c) = event_index[idx]
        A_dct = exp(fractional_counts[event])
        a_dct = get_decision_given_context(theta=theta, type=t, decision=d, context=c)
        batch_sum_likelihood += A_dct * a_dct
    return batch_sum_likelihood


def batch_accumilate_likelihood_with_expected_counts(results):
    global data_likelihood
    data_likelihood += results


def get_likelihood_with_expected_counts_mp(theta, display=True):
    global fractional_counts, data_likelihood, event_index, cache_normalizing_decision
    data_likelihood = 0.0
    cache_normalizing_decision = {}
    cpu_count = multiprocessing.cpu_count()
    pool = Pool(processes=cpu_count)  # uses all available CPUs
    batches_fractional_counts = np.array_split(range(len(event_index)), cpu_count)
    for batch_of_fc in batches_fractional_counts:
        pool.apply_async(batch_likelihood_with_expected_counts, args=(theta, batch_of_fc),
                         callback=batch_accumilate_likelihood_with_expected_counts)
    pool.close()
    pool.join()

    reg = np.sum(theta ** 2)
    data_likelihood -= (rc * reg)
    if display:
        print '\tec:', data_likelihood
    return -data_likelihood


def batch_gradient(theta, batch_events):
    global fractional_counts, feature_index, event_grad, rc, dictionary_features
    assert len(theta) == len(feature_index)
    eg = {}
    try:
        for event_j in batch_events:
            if not isinstance(event_j, tuple):
                event_j = tuple(event_j)

            (t, dj, cj) = event_j
            if t == E_TYPE:
                f_val, f = \
                    get_wa_features_fired(dictionary_features=dictionary_features, type=t, context=cj, decision=dj)[0]
                a_dp_ct = exp(get_decision_given_context(theta, decision=dj, context=cj, type=t)) * f_val
                sum_feature_j = 0.0
                norm_events = [(t, dp, cj) for dp in normalizing_decision_map[t, cj]]
                for event_i in norm_events:
                    A_dct = exp(fractional_counts.get(event_i, 0.0))
                    if event_i == event_j:
                        (ti, di, ci) = event_i
                        fj, f = get_wa_features_fired(dictionary_features=dictionary_features, type=ti, context=ci,
                                                      decision=di)[0]
                    else:
                        fj = 0.0
                    sum_feature_j += A_dct * (fj - a_dp_ct)
                eg[event_j] = sum_feature_j  # - abs(theta[event_j])  # this is the regularizing term
    except Exception, err:
        print 'error in batch gradient!'

        # print traceback.print_stack()
        print traceback.format_exc()
        raise BaseException('error in batch grad')
    return eg


def batch_accumilate_gradient(result):
    global event_grad

    for event_j in result:
        if event_j in event_grad:
            print 'what is going on here'
            raise 'should this happen?'
        else:
            event_grad[event_j] = result[event_j]


def get_gradient(theta):
    global fractional_counts, feature_index, event_grad, rc
    event_grad = {}
    cpu_count = multiprocessing.cpu_count()
    pool = Pool(processes=cpu_count)  # uses all available CPUs
    batch_fractional_counts = np.array_split(fractional_counts.keys(), cpu_count)
    for batch_event_j in batch_fractional_counts:
        pool.apply_async(batch_gradient, args=(theta, batch_event_j), callback=batch_accumilate_gradient)
    pool.close()
    pool.join()

    grad = -2 * rc * theta  # l2 regularization with lambda 0.5
    for e in event_grad:
        feats = events_to_features[e]
        for f in feats:
            grad[feature_index[f]] += event_grad[e]

    return -grad


def get_diagonal_tension(mnd, dt):
    global trellis, data_likelihood, rc, fractional_counts, feature_index, num_toks, emp_feat
    emp_feat_norm = emp_feat / num_toks
    mod_feat = 0
    for m, n in mnd:
        for j in xrange(1, m):
            mod_feat += mnd[m, n] * compute_d_log_z(j, m, n, dt)

    mod_feat_norm = mod_feat / num_toks
    print emp_feat_norm, mod_feat_norm, dt
    dt += (emp_feat_norm - mod_feat_norm) * 20
    if dt < 0.1:
        dt = 0.1
    elif dt > 14:
        dt = 14
    return dt


def gradient_check_em():
    global EPS, feature_index
    init_theta = initialize_theta(None)
    f_approx = {}
    for f in feature_index:
        theta_plus = copy.deepcopy(init_theta)
        theta_minus = copy.deepcopy(init_theta)
        theta_plus[feature_index[f]] = init_theta[feature_index[f]] + EPS
        get_likelihood(theta_plus)  # updates fractional counts
        val_plus = get_likelihood_with_expected_counts_mp(theta_plus)
        theta_minus[feature_index[f]] = init_theta[feature_index[f]] - EPS
        get_likelihood(theta_minus)  # updates fractional counts
        val_minus = get_likelihood_with_expected_counts_mp(theta_minus)
        f_approx[f] = (val_plus - val_minus) / (2 * EPS)

    my_grad = get_gradient(init_theta)
    diff = []
    for k in sorted(f_approx):
        diff.append(abs(my_grad[feature_index[k]] - f_approx[k]))
        print str(round(my_grad[feature_index[k]] - f_approx[k], 3)).center(10), str(
            round(my_grad[feature_index[k]], 5)).center(10), \
            str(round(f_approx[k], 5)).center(10), k
    f_approx = sorted([(feature_index[k], v) for k, v in f_approx.items()])
    f_approx = np.array([v for k, v in f_approx])

    print 'component difference:', round(sum(diff), 3), \
        'cosine similarity:', utils.cosine_sim(f_approx, my_grad), \
        ' sign difference', utils.sign_difference(f_approx, my_grad)


def gradient_check_lbfgs():
    global EPS, feature_index
    init_theta = initialize_theta(None, feature_index)
    chk_grad = utils.gradient_checking(init_theta, EPS, get_likelihood)
    my_grad = get_gradient(init_theta)
    diff = []
    for f in sorted(feature_index):  # xrange(len(chk_grad)):
        k = feature_index[f]
        diff.append(abs(my_grad[k] - chk_grad[k]))
        print str(round(my_grad[k] - chk_grad[k], 5)).center(10), str(
            round(my_grad[k], 5)).center(10), \
            str(round(chk_grad[k], 5)).center(10), f

    print 'component difference:', round(sum(diff), 3), \
        'cosine similarity:', utils.cosine_sim(chk_grad, my_grad), \
        ' sign difference', utils.sign_difference(chk_grad, my_grad)


def batch_sgd(obs_id, sgd_theta, sum_square_grad):
    # print _, obs_id

    event_observed = [event_index[eo] for eo in events_per_trellis[obs_id]]
    eg = batch_gradient(sgd_theta, event_observed)
    gdu = np.array([float('inf')] * len(sgd_theta))
    grad = np.zeros(np.shape(sgd_theta))  # -2 * rc * theta  # l2 regularization with lambda 0.5
    for e in eg:
        feats = events_to_features[e]
        for f in feats:
            grad[feature_index[f]] += eg[e]
            gdu[feature_index[f]] = du[feature_index[f]]

    grad_du = -2 * rc * np.divide(sgd_theta, gdu)
    grad += grad_du
    sum_square_grad += (grad ** 2)
    eta_t = eta0 / np.sqrt(I + sum_square_grad)
    sgd_theta += np.multiply(eta_t, grad)
    return obs_id


def batch_sgd_accumilate(obs_ids):
    # print obs_id
    pass


def write_logs(theta, current_iter):
    global max_beam_width, max_jump_width, trellis, feature_index, fractional_counts
    feature_val_typ = 'bin' if options.feature_values is None else 'real'
    name_prefix = '.'.join(
        ['mp', options.algorithm, str(rc), 'fast-model1', feature_val_typ])
    if current_iter is not None:
        name_prefix += '.' + str(current_iter)
    write_weights(theta, name_prefix + '.' + options.output_weights, feature_index)
    write_probs(theta, name_prefix + '.' + options.output_probs, fractional_counts, get_decision_given_context)

    if options.source_test is not None and options.target_test is not None:
        source_test = [s.strip().split() for s in open(options.source_test, 'r').readlines()]
        target_test = [t.strip().split() for t in open(options.target_test, 'r').readlines()]
        trellis = populate_trellis(source_test, target_test, max_jump_width, max_beam_width)

    write_alignments(theta, name_prefix + '.' + options.output_alignments, trellis, get_model1_forward)
    write_alignments_col(theta, name_prefix + '.' + options.output_alignments, trellis, get_model1_forward)
    write_alignments_col_tok(theta, name_prefix + '.' + options.output_alignments, trellis, source_test, target_test,
                             get_model1_forward)


if __name__ == "__main__":
    trellis = []

    opt = OptionParser()
    opt.add_option("-t", dest="target_corpus", default="experiment/data/dev.small.es")
    opt.add_option("-s", dest="source_corpus", default="experiment/data/dev.small.en")
    opt.add_option("--tt", dest="target_test", default="experiment/data/dev.small.es")
    opt.add_option("--ts", dest="source_test", default="experiment/data/dev.small.en")
    opt.add_option("--df", dest="dict_features", default=None)
    opt.add_option("--iw", dest="input_weights", default=None)
    opt.add_option("--fv", dest="feature_values", default=None)
    opt.add_option("--ow", dest="output_weights", default="theta", help="extention of trained weights file")
    opt.add_option("--oa", dest="output_alignments", default="alignments", help="extension of alignments files")
    opt.add_option("--op", dest="output_probs", default="probs", help="extension of probabilities")
    opt.add_option("-g", dest="test_gradient", default="false")
    opt.add_option("-r", dest="regularization_coeff", default="0.0")
    opt.add_option("-a", dest="algorithm", default="EM",
                   help="use 'EM' 'LBFGS' 'SGD'")

    (options, _) = opt.parse_args()
    rc = float(options.regularization_coeff)
    source, source_types = load_corpus_file(options.source_corpus)
    target, target_types = load_corpus_file(options.target_corpus)
    num_toks = len(open(options.target_corpus, 'r').read().split())
    diagonal_tension = 4.0
    trellis = populate_trellis(source, target, max_jump_width, max_beam_width)
    dictionary_features = load_dictionary_features(options.dict_features)
    events_to_features, features_to_events, feature_index, feature_counts, event_index, event_to_event_index, event_counts, normalizing_decision_map, du = populate_features(
        trellis, source, target, IBM_MODEL_1, dictionary_features)

    mn_list = [(len(trg) - 2, len(src) - 1) for trg, src in zip(target, source)]
    mn_dict = {}
    for mn in mn_list:
        mn_dict[mn] = mn_dict.get(mn, 0) + 1

    snippet = "#" + str(opt.values) + "\n"
    num_iterations = 10

    if options.algorithm == "LBFGS":
        if options.test_gradient.lower() == "true":
            gradient_check_lbfgs()
        else:
            print 'skipping gradient check...'
            init_theta = initialize_theta(options.input_weights, feature_index)
            t1 = minimize(get_likelihood, init_theta, method='L-BFGS-B', jac=get_gradient, tol=1e-3,
                          options={'maxiter': num_iterations})
            theta = t1.x

    elif options.algorithm == "EM":
        if options.test_gradient.lower() == "true":
            gradient_check_em()
        else:
            print 'skipping gradient check...'
            theta = initialize_theta(options.input_weights, feature_index)
            new_e = get_likelihood(theta)
            exp_new_e = get_likelihood_with_expected_counts_mp(theta)
            print 'new_e', new_e
            print 'exp_new_e', exp_new_e

            old_e = float('-inf')
            converged = False
            iterations = 0

            while not converged and iterations < num_iterations:
                t1 = minimize(get_likelihood_with_expected_counts_mp, theta, method='L-BFGS-B', jac=get_gradient,
                              tol=1e-3,
                              options={'maxfun': 5})
                theta = t1.x

                if 0 < iterations < num_iterations - 1:
                    for rep in xrange(8):
                        diagonal_tension = get_diagonal_tension(mn_dict, diagonal_tension)

                new_e = get_likelihood(theta)  # this will also update expected counts
                converged = round(abs(old_e - new_e), 1) == 0.0
                old_e = new_e
                iterations += 1
    elif options.algorithm == "EM-SGD":
        if options.test_gradient.lower() == "true":
            gradient_check_em()
        else:
            print 'skipping gradient check...'
            print 'populating events per trellis...'
            populate_events_per_trellis()
            print 'done...'
            theta = initialize_theta(options.input_weights, feature_index)
            new_e = get_likelihood(theta)
            exp_new_e = get_likelihood_with_expected_counts_mp(theta)
            old_e = float('-inf')
            converged = False
            iterations = 0
            ids = range(len(trellis))

            while not converged and iterations < num_iterations:
                eta0 = 1.0
                sum_square_grad = np.zeros(np.shape(theta))
                I = 1.0
                for _ in range(2):
                    random.shuffle(ids)
                    for obs_id in ids:
                        print _, obs_id
                        event_observed = [event_index[eo] for eo in events_per_trellis[obs_id]]
                        eg = batch_gradient(theta, event_observed)
                        grad = -2 * rc * theta  # l2 regularization with lambda 0.5
                        for e in eg:
                            feats = events_to_features[e]
                            for f in feats:
                                grad[feature_index[f]] += eg[e]
                        sum_square_grad += (grad ** 2)
                        eta_t = eta0 / np.sqrt(I + sum_square_grad)
                        theta += np.multiply(eta_t, grad)

                if 0 < iterations < num_iterations - 1:
                    for rep in xrange(8):
                        diagonal_tension = get_diagonal_tension(mn_dict, diagonal_tension)

                new_e = get_likelihood(theta)  # this will also update expected counts
                converged = round(abs(old_e - new_e), 2) == 0.0
                old_e = new_e
                iterations += 1
    elif options.algorithm == "EM-SGD-PARALLEL":
        if options.test_gradient.lower() == "true":
            gradient_check_em()
        else:
            print 'skipping gradient check...'
            print 'populating events per trellis...'
            populate_events_per_trellis()
            print 'done...'

            init_theta = initialize_theta(options.input_weights, feature_index)
            shared_sgd_theta = sharedmem.zeros(np.shape(init_theta))
            shared_sgd_theta += init_theta
            new_e = get_likelihood(shared_sgd_theta)
            old_e = float('-inf')
            converged = False
            iterations = 0
            ids = range(len(trellis))

            while not converged and iterations < num_iterations:
                eta0 = 1.0
                shared_sum_squared_grad = sharedmem.zeros(np.shape(shared_sgd_theta))
                I = 1.0
                for _ in range(2):
                    random.shuffle(ids)
                    cpu_count = multiprocessing.cpu_count()
                    pool = Pool(processes=cpu_count)
                    # batches = np.array_split(ids, cpu_count)
                    for obs_id in ids:
                        pool.apply_async(batch_sgd, args=(obs_id, shared_sgd_theta, shared_sum_squared_grad),
                                         callback=batch_sgd_accumilate)
                    pool.close()
                    pool.join()

                if 0 < iterations < num_iterations - 1:
                    for rep in xrange(8):
                        diagonal_tension = get_diagonal_tension(mn_dict, diagonal_tension)

                new_e = get_likelihood(shared_sgd_theta)  # this will also update expected counts
                converged = round(abs(old_e - new_e), 2) == 0.0
                old_e = new_e
                iterations += 1
            theta = shared_sgd_theta
    else:
        print 'wrong option for algorithm...'
        exit()

    if options.test_gradient.lower() == "true":
        pass
    else:
        write_logs(theta, current_iter=None)
