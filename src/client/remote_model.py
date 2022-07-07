# this code is in active development, interfaces may change
import os
from typing import Optional, Tuple, Union

import hivemind
from hivemind import DHT, get_logger, use_hivemind_log_handler

from src.bloom.from_pretrained import CLIENT_BRANCH, _load_state_dict
from src.bloom.model import BloomConfig, BloomForCausalLM, BloomModel, BloomPreTrainedModel
from src.client.remote_sequential import RemoteSequential
from src.data_structures import UID_DELIMITER

use_hivemind_log_handler("in_root_logger")
logger = get_logger(__file__)


class DistributedBloomConfig(BloomConfig):
    """
    A bloom config that contains information about DHT peers.
    To create a distributed model, one must provide dht_prefix and either initial_peers or dht.
    """

    initial_peers: Tuple[str, ...] = ()  # a list of initial peers for hivemind DHT
    dht_prefix: str  # a prefix for all dht keys that correspond to this model (usually equal to model name)
    dht: Optional[hivemind.DHT] = None  # a running DHT instance, e.g. when using the same DHT for multiple models


class DistributedBloomModel(BloomModel):
    """BloomModel, but all transformer layers are hosted by the swarm"""

    def __init__(self, config: DistributedBloomConfig):
        assert self.config.dht_prefix, "Could not find dht_prefix in config, please create model with dht_prefix=..."
        assert (
            self.config.initial_peers or config.dht
        ), "Please specify initial_peers=list(...) or dht=hivemind.DHT(...)"

        n_layer, config.n_layer = config.n_layer, 0  # temporarily set n_layer to 0 to prevent layer initialization
        super().__init__(config)
        assert len(self.h) == 0
        config.n_layer = n_layer

        dht = (
            config.dht
            if config.dht is not None
            else hivemind.DHT(initial_peers=config.initial_peers, client_mode=True, start=True)
        )
        assert isinstance(dht, hivemind.DHT) and dht.is_alive(), "dht must be a running hivemind.DHT instance"
        self.h = RemoteSequential(config, dht, config.dht_prefix)


class DistributedBloomForCausalLM(BloomForCausalLM):
    """DistributedBloomForCausalLM, but all transformer layers are hosted by the swarm"""

    def __init__(self, config: DistributedBloomConfig):
        BloomPreTrainedModel().__init__(config)
        self.transformer = DistributedBloomModel(config)
        # Initialize weights and apply final processing
        self.post_init()