# Copyright (c) OpenMMLab. All rights reserved.
import torch
import torch.nn as nn
from mmcv.runner import BaseModule

from mmselfsup.utils import concat_all_gather
from ..builder import HEADS, build_neck


@HEADS.register_module()
class MoCoV3Head(BaseModule):
    """Head for MoCo v3 algorithms.

    This head builds a predictor, which can be any registered neck component.
    It also implements latent contrastive loss between two forward features.
    Part of the code is modified from:
    `<https://github.com/facebookresearch/moco-v3/blob/main/moco/builder.py>`_.

    Args:
        predictor (dict): Config dict for module of predictor.
        temperature (float): The temperature hyper-parameter that
            controls the concentration level of the distribution.
            Defaults to 1.0.
    """

    def __init__(self, predictor, temperature=1.0):
        super(MoCoV3Head, self).__init__()
        self.predictor = build_neck(predictor)
        self.temperature = temperature

    def forward(self, base_out, momentum_out):
        """Forward head.

        Args:
            base_out (Tensor): NxC features from base_encoder.
            momentum_out (Tensor): NxC features from momentum_encoder.

        Returns:
            dict[str, Tensor]: A dictionary of loss components.
        """
        # predictor computation
        pred = self.predictor([base_out])[0] # Query 编码器额外增加 Prediction Head

        # normalize
        pred = nn.functional.normalize(pred, dim=1)
        target = nn.functional.normalize(momentum_out, dim=1)

        # get negative samples
        target = concat_all_gather(target)

        # Einstein sum is more intuitive # 这里应该跟v1的那个 'nc,ck->nk' 差求不多，算出来的就是n中的某个样本和m里的某个样本二者之间的logit
        logits = torch.einsum('nc,mc->nm', [pred, target]) / self.temperature

        # generate labels
        batch_size = logits.shape[0]
        labels = (torch.arange(batch_size, dtype=torch.long) +
                  batch_size * torch.distributed.get_rank()).cuda()

        loss = 2 * self.temperature * nn.CrossEntropyLoss()(logits, labels) # 这个地方骚啊，比v1那个写法还骚，其实就是nm矩阵的对角线元素是gt，其它的不是
        return dict(loss=loss)
