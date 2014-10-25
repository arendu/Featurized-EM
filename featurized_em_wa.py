__author__ = 'arenduchintala'

from optparse import OptionParser
from math import exp, log
from DifferentiableFunction import DifferentiableFunction
import numpy as np
import FeatureEng as FE
from scipy.optimize import fmin_l_bfgs_b
from scipy.optimize import approx_fprime
import pdb
import utils
from pprint import pprint
from collections import defaultdict
import itertools

global BOUNDARY_STATE, END_STATE, SPLIT, E_TYPE, T_TYPE, possible_states, normalizing_decision_map
global cache_normalizing_decision, features_to_conditional_arcs, conditional_arcs_to_features
global trellis
trellis = []
cache_normalizing_decision = {}
BOUNDARY_STATE = "###"
NULL = "NULL"
SPLIT = "###/###"
E_TYPE = "EMISSION"
E_TYPE_PRE = "PREFIX_FEATURE"
E_TYPE_SUF = "SUFFIX_FEATURE"
T_TYPE = "TRANSITION"
S_TYPE = "STATE"
ALL = "ALL_STATES"
fractional_counts = {}
conditional_arcs_to_features = {}
features_to_conditional_arcs = {}
feature_index = {}
conditional_arc_index = {}
possible_states = {}
possible_obs = {}
normalizing_decision_map = {}


def populate_features():
    global trellis, feature_index
    for treli in trellis:
        for idx in treli:
            for t_idx, t_tok, s_idx, s_tok in treli[idx]:
                s = (s_idx, s_tok)
                t = (t_idx, t_tok)
                ff = FE.get_wa_features_fired(type=E_TYPE, decision=t_tok, context=s_tok)
                for f in ff:
                    feature_index[f] = feature_index.get(f, 0) + 1
                    ca2f = conditional_arcs_to_features.get((t_tok, s_tok), set([]))
                    ca2f.add(f)
                    conditional_arcs_to_features[t_tok, s_tok] = ca2f
                    f2ca = features_to_conditional_arcs.get(f, set([]))
                    f2ca.add((t_tok, s_tok))
                    features_to_conditional_arcs[f] = f2ca


def populate_arcs_to_features():
    global features_to_conditional_arcs, conditional_arcs_to_features, feature_index, conditional_arc_index
    for d, c in itertools.product(possible_obs[ALL], possible_states[ALL]):
        if c == BOUNDARY_STATE and d != BOUNDARY_STATE:
            pass
        else:
            fired_features = FE.get_pos_features_fired(E_TYPE, decision=d, context=c)
            fs = conditional_arcs_to_features.get((E_TYPE, d, c), set([]))
            fs = fs.union(fired_features)
            conditional_arcs_to_features[E_TYPE, d, c] = fs
            conditional_arc_index[E_TYPE, d, c] = conditional_arc_index.get((E_TYPE, d, c), len(conditional_arc_index))
            for ff in fired_features:
                feature_index[ff] = feature_index.get(ff, len(feature_index))
                cs = features_to_conditional_arcs.get(ff, set([]))
                cs.add((E_TYPE, d, c))
                features_to_conditional_arcs[ff] = cs

    for d, c in itertools.product(possible_states[ALL], possible_states[ALL]):
        if d == BOUNDARY_STATE and c == BOUNDARY_STATE:
            pass
        else:
            fired_features = FE.get_pos_features_fired(T_TYPE, decision=d, context=c)
            fs = conditional_arcs_to_features.get((T_TYPE, d, c), set([]))
            fs = fs.union(fired_features)
            conditional_arcs_to_features[T_TYPE, d, c] = fs
            conditional_arc_index[T_TYPE, d, c] = conditional_arc_index.get((T_TYPE, d, c), len(conditional_arc_index))
            for ff in fired_features:
                feature_index[ff] = feature_index.get(ff, len(feature_index))
                cs = features_to_conditional_arcs.get(ff, set([]))
                cs.add((T_TYPE, d, c))
                features_to_conditional_arcs[ff] = cs


def populate_normalizing_terms():
    for treli in trellis:
        for idx in treli:
            for t_idx, t_tok, s_idx, s_tok in treli[idx]:
                s = (s_idx, s_tok)
                t = (t_idx, t_tok)
                ndm = normalizing_decision_map.get((E_TYPE, s_tok), set([]))
                ndm.add(t_tok)
                normalizing_decision_map[E_TYPE, s_tok] = ndm


def get_decision_given_context(theta, type, decision, context):
    global normalizing_decision_map, cache_normalizing_decision
    fired_features = FE.get_wa_features_fired(type=type, context=context, decision=decision)
    theta_dot_features = sum([theta[f] for f in fired_features if f in theta])
    # TODO: weights theta are initialized to 0.0
    # TODO: this initialization should be done in a better way
    if (type, context) in cache_normalizing_decision:
        theta_dot_normalizing_features = cache_normalizing_decision[type, context]
    else:
        normalizing_decisions = normalizing_decision_map[type, context]
        theta_dot_normalizing_features = float('-inf')
        for d in normalizing_decisions:
            d_features = FE.get_wa_features_fired(type=type, context=context, decision=d)
            try:
                theta_dot_normalizing_features = utils.logadd(theta_dot_normalizing_features,
                                                              sum([theta[f] for f in d_features if f in theta]))
            except OverflowError:
                pdb.set_trace()
        cache_normalizing_decision[type, context] = theta_dot_normalizing_features
    log_prob = theta_dot_features - theta_dot_normalizing_features
    return log_prob  # log(prob)


def get_possible_states(o):
    if o == BOUNDARY_STATE:
        return [BOUNDARY_STATE]
    # elif o in possible_states:
    # return list(possible_states[o])
    else:
        return list(possible_states[ALL] - set([BOUNDARY_STATE]))


def get_backwards(theta, obs, alpha_pi):
    n = len(obs) - 1  # index of last word
    COMPOSITE_BOUNDARY_STATE = (n, '###', n, '###')
    beta_pi = {(n, COMPOSITE_BOUNDARY_STATE): 0.0}
    S = alpha_pi[(n, COMPOSITE_BOUNDARY_STATE)]  # from line 13 in pseudo code
    for k in range(n, 0, -1):
        for v in obs[k]:
            tk, t_tok, aj, sj = v
            e = get_decision_given_context(theta, E_TYPE, decision=t_tok, context=sj)
            pb = beta_pi[(k, v)]
            # accumulate_fc(type=S_TYPE, alpha=alpha_pi[(k, v)], beta=beta_pi[k, v], k=k, S=S, d=t_tok)
            accumulate_fc(type=E_TYPE, alpha=alpha_pi[(k, v)], beta=beta_pi[k, v], S=S, d=t_tok, c=sj)
            for u in obs[k - 1]:
                tk_1, t_tok_1, aj_1, sj_1 = u
                q = log(1.0 / len(obs[k]))  # transition in model1 is uniform
                # q = get_decision_given_context(theta, T_TYPE, v, u)
                p = q + e
                beta_p = pb + p  # The beta includes the emission probability
                new_pi_key = (k - 1, u)
                if new_pi_key not in beta_pi:  # implements lines 16
                    beta_pi[new_pi_key] = beta_p
                else:
                    beta_pi[new_pi_key] = utils.logadd(beta_pi[new_pi_key], beta_p)
                # print 'beta     ', new_pi_key, '=', beta_pi[new_pi_key], exp(beta_pi[new_pi_key])
                # alpha_pi[(k - 1, u)] + p + beta_pi[(k, v)] - S
                accumulate_fc(type=T_TYPE, alpha=alpha_pi[k - 1, u], beta=beta_pi[k, v], q=q, e=e, d=aj, c=aj_1, S=S)
    return S, beta_pi


def get_viterbi_and_forward(theta, obs):
    COMPOSITE_BOUNDARY_STATE = (0, '###', 0, '###')
    pi = {(0, COMPOSITE_BOUNDARY_STATE): 0.0}
    alpha_pi = {(0, COMPOSITE_BOUNDARY_STATE): 0.0}
    arg_pi = {(0, COMPOSITE_BOUNDARY_STATE): []}
    for k in range(1, len(obs)):  # the words are numbered from 1 to n, 0 is special start character
        for v in obs[k]:  # [1]:
            max_prob_to_bt = {}
            sum_prob_to_bt = []
            for u in obs[k - 1]:  # [1]:
                tk, t_tok, aj, sj = v
                tk_1, t_tok_1, aj_1, sj_1 = u
                # TODO: figure out how to send decision and context here, and get back a probability
                # q = get_decision_given_context(theta, T_TYPE, v, u)
                q = log(1.0 / len(obs[k]))  # transition in model1 is uniform
                e = get_decision_given_context(theta, E_TYPE, decision=t_tok, context=sj)
                # print 'q,e', q, e
                # p = pi[(k - 1, u)] * q * e
                # alpha_p = alpha_pi[(k - 1, u)] * q * e
                p = pi[(k - 1, u)] + q + e
                alpha_p = alpha_pi[(k - 1, u)] + q + e
                if len(arg_pi[(k - 1, u)]) == 0:
                    bt = [u]
                else:
                    bt = [arg_pi[(k - 1, u)], u]
                max_prob_to_bt[p] = bt
                sum_prob_to_bt.append(alpha_p)

            max_bt = max_prob_to_bt[max(max_prob_to_bt)]
            new_pi_key = (k, v)
            pi[new_pi_key] = max(max_prob_to_bt)
            # print 'mu   ', new_pi_key, '=', pi[new_pi_key], exp(pi[new_pi_key])
            alpha_pi[new_pi_key] = utils.logadd_of_list(sum_prob_to_bt)
            # print 'alpha', new_pi_key, '=', alpha_pi[new_pi_key], exp(alpha_pi[new_pi_key])
            arg_pi[new_pi_key] = max_bt

    max_bt = max_prob_to_bt[max(max_prob_to_bt)]
    max_p = max(max_prob_to_bt)
    max_bt = utils.flatten_backpointers(max_bt)
    return max_bt, max_p, alpha_pi


def reset_fractional_counts():
    global fractional_counts, cache_normalizing_decision
    fractional_counts = {}  # dict((k, float('-inf')) for k in conditional_arc_index)
    cache_normalizing_decision = {}


def accumulate_fc(type, alpha, beta, d, S, c=None, k=None, q=None, e=None):
    global fractional_counts
    if type == T_TYPE:
        update = alpha + q + e + beta - S
        fractional_counts[T_TYPE, d, c] = utils.logadd(update, fractional_counts.get((T_TYPE, d, c,), float('-inf')))
    elif type == E_TYPE:
        update = alpha + beta - S  # the emission should be included in alpha
        fractional_counts[E_TYPE, d, c] = utils.logadd(update, fractional_counts.get((E_TYPE, d, c,), float('-inf')))
    elif type == S_TYPE:
        update = alpha + beta - S
        old = fractional_counts.get((S_TYPE, k, d), float('-inf'))
        fractional_counts[S_TYPE, k, d] = utils.logadd(update, old)
        old = fractional_counts.get((S_TYPE, None, d), float('-inf'))
        fractional_counts[S_TYPE, None, d] = utils.logadd(update, old)
    else:
        raise "Wrong type"


def write_alignments(theta, save_align):
    global trellis
    write_align = open(save_align, 'w')
    for idx, obs in enumerate(trellis[:]):
        max_bt, max_p, alpha_pi = get_viterbi_and_forward(theta, obs)
        w = ' '.join([str(tar_i - 1) + '-' + str(src_i - 1) for src_i, src, tar_i, tar in max_bt if
                      (tar_i != NULL and tar_i > 0 and src_i > 0)])
        write_align.write(w + '\n')
    write_align.flush()
    write_align.close()


def get_likelihood(theta):
    # theta = dict((k, theta_list[v]) for k, v in feature_index.items())
    global trellis
    reset_fractional_counts()
    data_likelihood = 0.0
    for idx, obs in enumerate(trellis[:]):
        max_bt, max_p, alpha_pi = get_viterbi_and_forward(theta, obs)
        S, beta_pi = get_backwards(theta, obs, alpha_pi)
        data_likelihood += S

    reg = sum([t ** 2 for k, t in theta.items()])
    print 'accumulating', data_likelihood - (0.5 * reg)  # , ' '.join(obs)
    return data_likelihood - (0.5 * reg)


def get_gradient(theta):
    fractional_count_grad = {}
    for event in fractional_counts:
        (type, d, c) = event
        # print event, fractional_counts[event]
        if type == E_TYPE:
            Adc = exp(fractional_counts.get(event, float('-inf')))
            a_dc = exp(get_decision_given_context(theta, type=E_TYPE, decision=d, context=c))
            fractional_count_grad[type, d, c] = Adc * (1 - a_dc)

    grad = {}
    for fcg_event in fractional_count_grad:
        (type, d, c) = fcg_event
        if type == E_TYPE:
            for f in conditional_arcs_to_features[d, c]:
                grad[f] = fractional_count_grad[fcg_event] + grad.get(f, 0.0)

    for t in theta:
        if t not in grad:
            grad[t] = 0.0 - (0.5 * theta[t])
        else:
            grad[t] -= (0.5 * theta[t])
    return grad


def populate_trellis(source_corpus, target_corpus):
    global trellis
    span = 10  # creates a span of +/- span centered around current token
    for s_sent, t_sent in zip(source_corpus, target_corpus):
        t_sent.insert(0, BOUNDARY_STATE)
        s_sent.insert(0, BOUNDARY_STATE)
        t_sent.append(BOUNDARY_STATE)
        s_sent.append(BOUNDARY_STATE)
        current_trellis = {}
        for t_idx, t_tok in enumerate(t_sent):
            if t_tok == BOUNDARY_STATE:
                current_trellis[t_idx] = [(t_idx, BOUNDARY_STATE, t_idx, BOUNDARY_STATE)]
            else:
                start = t_idx - span if t_idx - span >= 0 else 0
                end = t_idx + span + 1
                current_trellis[t_idx] = [(t_idx, t_tok, s_idx + start, s_tok) for s_idx, s_tok in
                                          enumerate(s_sent[start:end]) if s_tok != BOUNDARY_STATE] + [
                                             (t_idx, t_tok, NULL, NULL)]
        trellis.append(current_trellis)


if __name__ == "__main__":
    trellis = []
    possible_states = defaultdict(set)
    possible_obs = defaultdict(set)
    opt = OptionParser()
    opt.add_option("-t", dest="target_corpus", default="data/toy2/en")
    opt.add_option("-f", dest="source_corpus", default="data/toy2/fr")
    opt.add_option("-o", dest="save", default="theta.out")
    opt.add_option("-a", dest="alignments", default="alignments.out")
    (options, _) = opt.parse_args()
    source = [s.strip().split() for s in open(options.source_corpus, 'r').readlines() if s.strip() != '']
    target = [s.strip().split() for s in open(options.target_corpus, 'r').readlines() if s.strip() != '']
    populate_trellis(source, target)
    populate_features()
    populate_normalizing_terms()
    init_theta = dict((k, 1.0) for k in feature_index)
    F = DifferentiableFunction(get_likelihood, get_gradient)
    (fopt, theta, return_status) = F.maximize(init_theta)
    """
    populate_arcs_to_features()
    init_theta = dict((k, np.random.uniform(-0.1, 0.1)) for k in feature_index)
    """
    # print return_status
    write_theta = open(options.save, 'w')
    for t in sorted(theta):
        write_theta.write(t[0] + '\t' + t[1] + "\t" + str(theta[t]) + '' + "\n")
    write_theta.flush()
    write_theta.close()

    write_alignments(theta, options.alignments)