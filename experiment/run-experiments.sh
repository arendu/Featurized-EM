#!/bin/sh
SOURCE_FULL="source_full.tmp"
TARGET_FULL="target_full.tmp"
SOURCE_TRAIN="data/train.en"
TARGET_TRAIN="data/train.es"
SOURCE_TEST="data/dev.en"
TARGET_TEST="data/dev.es"
KEY="data/dev.key"
MODEL="model1"
ALGO="EM"
echo "training files:" $SOURCE_TRAIN ","  $TARGET_TRAIN
echo "testing  files:" $SOURCE_TEST "," $TARGET_TEST
touch $SOURCE_FULL
touch $TARGET_FULL
cat $SOURCE_TEST > $SOURCE_FULL
cat $SOURCE_TRAIN >> $SOURCE_FULL
cat $TARGET_TEST > $TARGET_FULL
cat $TARGET_TRAIN >> $TARGET_FULL

python initial_translation.py  -s $SOURCE_FULL -t $TARGET_FULL  -o initial.trans -m uniform
for ALGO in "LBFGS" "EM"
do
  for RC in 0.0 0.005
  do
    time python ../featurized_em_wa_mp.py -s $SOURCE_FULL -t $TARGET_FULL -a $ALGO -m $MODEL --iw initial.trans.log --ts $SOURCE_TEST --tt $TARGET_TEST -r $RC
  done
done


for ALGO in "LBFGS" "EM"
do
  for RC in 0.0 0.005
  do
    echo ""
    echo "*********"$ALGO " RC:"$RC"********"
    echo ""
    python eval_alignment.py $KEY $ALGO.$RC.$MODEL.alignments.col
  done
done

python model1.py -s $SOURCE_FULL -t $TARGET_FULL -i initial.trans -p model1.probs -a model1.alignments -as $SOURCE_TEST -at $TARGET_TEST
echo ""
echo "********Baseline********"
echo ""
python eval_alignment.py $KEY model1.alignments


rm $SOURCE_FULL
rm $TARGET_FULL
