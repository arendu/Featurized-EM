#!/bin/sh
set -e
source /home/arenduc1/MachineTranslation/Featurized-EM/experiment/config.cfg
SOURCE_FULL="source_full.tmp"
TARGET_FULL="target_full.tmp"
DICT_PATH="data/dictionary_features.es-en"
MODEL="hybrid-model1"
echo "training files:" $SOURCE_TRAIN ","  $TARGET_TRAIN
echo "testing  files:" $SOURCE_TEST "," $TARGET_TEST
touch $SOURCE_FULL
touch $TARGET_FULL
cat $SOURCE_TEST > $SOURCE_FULL
cat $SOURCE_TRAIN >> $SOURCE_FULL
cat $TARGET_TEST > $TARGET_FULL
cat $TARGET_TRAIN >> $TARGET_FULL

python ${CODE_DIR}/initial_translation.py  -s $SOURCE_FULL -t $TARGET_FULL  -o $EXPERIMENTS_DIR/initial.trans
time python ${CODE_DIR}/model1.py -s $SOURCE_FULL -t $TARGET_FULL -i $EXPERIMENTS_DIR/initial.trans -p $EXPERIMENTS_DIR/model1.probs -a $EXPERIMENTS_DIR/model1.alignments --as $SOURCE_TEST --at $TARGET_TEST
for ALGO in "LBFGS" 
do
    for RC in 0.0
    do
        time python ${CODE_DIR}/use_hm1.py -s $SOURCE_FULL -t $TARGET_FULL -a $ALGO  --m1 $EXPERIMENTS_DIR/model1.probs --ts $SOURCE_TEST --tt $TARGET_TEST -r $RC --df $DICT_PATH --oa use
        #time python ${CODE_DIR}/hybrid_model1.py -s $SOURCE_FULL -t $TARGET_FULL -a $ALGO  --m1 $EXPERIMENTS_DIR/model1.probs --ts $SOURCE_TEST --tt $TARGET_TEST -r $RC --df $DICT_PATH
        #time python ${CODE_DIR}/hybrid_model1_mp.py -s $SOURCE_FULL -t $TARGET_FULL -a $ALGO  --m1 $EXPERIMENTS_DIR/model1.probs --ts $SOURCE_TEST --tt $TARGET_TEST -r $RC --df $DICT_PATH
        echo "."
    done
done



echo ""
echo "********Baseline********"
echo ""
python ${TOOLS_DIR}/eval_alignment.py $KEY $EXPERIMENTS_DIR/model1.alignments

for ALGO in "LBFGS" 
do
    for RC in 0.0
    do
        echo ""
        echo "*********SIMPLE "$ALGO " RC:"$RC"********"
        echo ""
        python ${TOOLS_DIR}/eval_alignment.py $KEY $EXPERIMENTS_DIR/sp.$ALGO.$RC.$MODEL.bin.use.col
        #python ${TOOLS_DIR}/eval_alignment.py $KEY $EXPERIMENTS_DIR/sp.$ALGO.$RC.$MODEL.bin.alignments.col
        #python ${TOOLS_DIR}/eval_alignment.py $KEY mp.$ALGO.$RC.$MODEL.bin.alignments.col
    done
done
echo "deleting files..."
rm $SOURCE_FULL
rm $TARGET_FULL
rm $EXPERIMENTS_DIR/initial.trans
rm $EXPERIMENTS_DIR/model1.probs
rm $EXPERIMENTS_DIR/model1.alignments
#rm $EXPERIMENTS_DIR/mp.*
#rm $EXPERIMENTS_DIR/sp.*
