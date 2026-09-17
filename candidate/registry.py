from candidate.manager import ORBCandidateManager
from candidate.ranking import PercentileRanking

CANDIDATE_MANAGER_REGISTRY = {"orb_candidate_manager": ORBCandidateManager}
RANKING_METHOD_REGISTRY = {"percentile": PercentileRanking}
