import random
import codecs
import sys
import nltk
# import logging
import re
import numpy as np
import pickle as pk
import utils
import pandas as pd
import csv

# 用于替换URL的占位符
url_replacer = '<url>'
# 初始化日志记录器
logger = utils.get_logger("Loading data...")
# 正则表达式用于匹配数字
num_regex = re.compile('^[+-]?[0-9]+\.?[0-9]*$')
# 参考分数数据类型
ref_scores_dtype = 'int32'
# 各个prompt的高分值设定
high_score = [0, 10, 5, 3, 3, 3, 3, 24, 48]

# 最大句子长度和最大句子数量的定义
MAX_SENTLEN = 50
MAX_SENTNUM = 100

# ASAP数据集各个prompt对应的分数范围
asap_ranges = {
    0: (0, 60),
    1: (2, 12),
    2: (1, 6),
    3: (0, 3),
    4: (0, 3),
    5: (0, 4),
    6: (0, 4),
    7: (0, 30),
    8: (0, 60)
}

def get_ref_dtype():
    """获取参考分数的数据类型"""
    return ref_scores_dtype

def tokenize(string):
    """对输入字符串进行标记化处理，处理'@'符号后的数字"""
    tokens = nltk.word_tokenize(string)
    for index, token in enumerate(tokens):
        if token == '@' and (index + 1) < len(tokens):
            tokens[index + 1] = '@' + re.sub('[0-9]+.*', '', tokens[index + 1])
            tokens.pop(index)
    return tokens

def get_score_range(prompt_id):
    """根据prompt_id返回对应的分数范围"""
    return asap_ranges[prompt_id]

def get_model_friendly_scores(scores_array, prompt_id_array):
    """将原始分数转换为0-1范围的模型友好分数"""
    for k, i in enumerate(prompt_id_array):
        if i == 1:
            minscore = 2
            maxscore = 12
        elif i == 2:
            minscore = 1
            maxscore = 6
        elif i in [3, 4]:
            minscore = 0
            maxscore = 3
        elif i in [5, 6]:
            minscore = 0
            maxscore = 4
        elif i == 7:
            minscore = 0
            maxscore = 30
        elif i == 8:
            minscore = 0
            maxscore = 60
        else:
            minscore = 1
            maxscore = 3

        scores_array[k] = (scores_array[k] - minscore) / (maxscore - minscore)
    return scores_array

def convert_to_dataset_friendly_scores(scores_array, prompt_id_array):
    """将模型友好分数转换为数据集友好分数"""
    i = prompt_id_array
    if i == 1:
        minscore = 2
        maxscore = 12
    elif i == 2:
        minscore = 1
        maxscore = 6
    elif i in [3, 4]:
        minscore = 0
        maxscore = 3
    elif i in [5, 6]:
        minscore = 0
        maxscore = 4
    elif i == 7:
        minscore = 0
        maxscore = 30
    elif i == 8:
        minscore = 0
        maxscore = 60
    else:
        minscore = 1
        maxscore = 3

    for k, i in enumerate(scores_array):
        scores_array[k] = scores_array[k] * (maxscore - minscore) + minscore
    return np.round(scores_array)

def is_number(token):
    """判断标记是否为数字"""
    return bool(num_regex.match(token))


def load_vocab(vocab_path):
    """从指定路径加载词汇表"""
    logger.info('Loading vocabulary from: ' + vocab_path)
    with open(vocab_path, 'rb') as vocab_file:
        vocab = pk.load(vocab_file)
    return vocab


def create_vocab(file_path, prompt_id, vocab_size, tokenize_text, to_lower):
    """创建词汇表"""
    logger.info('Creating vocabulary from: ' + file_path)
    total_words, unique_words = 0, 0
    word_freqs = {}
    with codecs.open(file_path, mode='r', encoding='UTF8') as input_file:
        input_file.readline()
        for line in input_file:
            tokens = line.strip().split('\t')
            essay_id = int(tokens[0])
            essay_set = int(tokens[1])
            content = tokens[2].strip()
            score = float(tokens[6])
            # print(tokens, essay_id, essay_set, content, score)
            if essay_set == prompt_id or prompt_id <= 0:
                if tokenize_text:
                    content = text_tokenizer(content, True, True, True)
                if to_lower:
                    content = [w.lower() for w in content]
                for word in content:
                    try:
                        word_freqs[word] += 1
                    except KeyError:
                        unique_words += 1
                        word_freqs[word] = 1
                    total_words += 1
    logger.info('  %i total words, %i unique words' % (total_words, unique_words))
    import operator
    sorted_word_freqs = sorted(word_freqs.items(), key=operator.itemgetter(1), reverse=True)
    if vocab_size <= 0:
        # Choose vocab size automatically by removing all singletons
        vocab_size = 0
        for word, freq in sorted_word_freqs:
            if freq > 1:
                vocab_size += 1
    vocab = {'<pad>': 0, '<unk>': 1, '<num>': 2}
    vcb_len = len(vocab)
    index = vcb_len
    for word, _ in sorted_word_freqs[:vocab_size - vcb_len]:
    # use top 4000 words
    #for word, _ in sorted_word_freqs:
        vocab[word] = index
        index += 1
    return vocab


def read_essays(file_path, prompt_id):
    """读取TSV文件中的作文，并返回作文列表及其ID"""
    logger.info('Reading tsv from: ' + file_path)
    essays_list = []
    essays_ids = []
    with codecs.open(file_path, mode='r', encoding='UTF8') as input_file:
        #input_file.next()
        for line in input_file:
            tokens = line.strip().split('\t')
            if int(tokens[1]) == prompt_id or prompt_id <= 0:
                essays_list.append(tokens[2].strip())
                essays_ids.append(int(tokens[0]))
    return essays_list, essays_ids


def replace_url(text):
    """替换文本中的URL为占位符"""
    replaced_text = re.sub('(http[s]?://)?((www)\.)?([a-zA-Z0-9]+)\.{1}((com)(\.(cn))?|(org))', url_replacer, text)
    return replaced_text


def text_tokenizer(text, replace_url_flag=True, tokenize_sent_flag=True, create_vocab_flag=False):
    """对文本进行标记化处理，返回处理后的句子标记"""
    text = replace_url(text)
    text = text.replace(u'"', u'')
    if "..." in text:
        text = re.sub(r'\.{3,}(\s+\.{3,})*', '...', text)
        # print text
    if "??" in text:
        text = re.sub(r'\?{2,}(\s+\?{2,})*', '?', text)
        # print text
    if "!!" in text:
        text = re.sub(r'\!{2,}(\s+\!{2,})*', '!', text)
        # print text

    # TODO here
    tokens = tokenize(text)
    if tokenize_sent_flag:
        text = " ".join(tokens)
        sent_tokens = tokenize_to_sentences(text, MAX_SENTLEN, create_vocab_flag)
        # print sent_tokens
        # sys.exit(0)
        # if not create_vocab_flag:
        #     print "After processed and tokenized, sentence num = %s " % len(sent_tokens)
        return sent_tokens
    else:
        raise NotImplementedError


def tokenize_to_sentences(text, max_sentlength, create_vocab_flag=False):
    """将长文本分割成句子"""
    # tokenize a long text to a list of sentences
    sents = re.split(r'(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\!|\?)\s', text)

    # Note
    # add special preprocessing for abnormal sentence splitting
    # for example, sentence1 entangled with sentence2 because of period "." connect the end of sentence1 and the begin of sentence2
    # see example: "He is running.He likes the sky". This will be treated as one sentence, needs to be specially processed.
    # 特殊处理因句号连缀的异常句子
    processed_sents = []
    for sent in sents:
        if re.search(r'(?<=\.{1}|\!|\?|\,)(@?[A-Z]+[a-zA-Z]*[0-9]*)', sent):
            s = re.split(r'(?=.{2,})(?<=\.{1}|\!|\?|\,)(@?[A-Z]+[a-zA-Z]*[0-9]*)', sent)
            # print sent
            # print s
            ss = " ".join(s)
            ssL = re.split(r'(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\!|\?)\s', ss)

            processed_sents.extend(ssL)
        else:
            processed_sents.append(sent)

    if create_vocab_flag:
        sent_tokens = [tokenize(sent) for sent in processed_sents]
        tokens = [w for sent in sent_tokens for w in sent]
        # print tokens
        return tokens
    # 处理句子长度
    # TODO here
    sent_tokens = []
    for sent in processed_sents:
        shorten_sents_tokens = shorten_sentence(sent, max_sentlength)
        sent_tokens.extend(shorten_sents_tokens)
    # if len(sent_tokens) > 90:
    #     print len(sent_tokens), sent_tokens
    return sent_tokens


def shorten_sentence(sent, max_sentlen):
    """处理TSV文件中的作文，将其转换为模型输入格式"""
    # handling extra long sentence, truncate to no more extra max_sentlen
    new_tokens = []
    sent = sent.strip()
    tokens = nltk.word_tokenize(sent)
    if len(tokens) > max_sentlen:
        # print len(tokens)
        # Step 1: split sentence based on keywords
        # split_keywords = ['because', 'but', 'so', 'then', 'You', 'He', 'She', 'We', 'It', 'They', 'Your', 'His', 'Her']
        split_keywords = ['because', 'but', 'so', 'You', 'He', 'She', 'We', 'It', 'They', 'Your', 'His', 'Her']
        k_indexes = [i for i, key in enumerate(tokens) if key in split_keywords]
        processed_tokens = []
        if not k_indexes:
            num = len(tokens) / max_sentlen
            k_indexes = [(i+1)*max_sentlen for i in range(int(num))]

        processed_tokens.append(tokens[0:k_indexes[0]])
        len_k = len(k_indexes)
        for j in range(len_k-1):
            processed_tokens.append(tokens[k_indexes[j]:k_indexes[j+1]])
        processed_tokens.append(tokens[k_indexes[-1]:])

        # Step 2: split sentence to no more than max_sentlen
        # if there are still sentences whose length exceeds max_sentlen
        for token in processed_tokens:
            if len(token) > max_sentlen:
                num = len(token) / max_sentlen
                s_indexes = [(i+1)*max_sentlen for i in range(int(num))]

                len_s = len(s_indexes)
                new_tokens.append(token[0:s_indexes[0]])
                for j in range(len_s-1):
                    new_tokens.append(token[s_indexes[j]:s_indexes[j+1]])
                new_tokens.append(token[s_indexes[-1]:])

            else:
                new_tokens.append(token)
    else:
            return [tokens]

    # print "Before processed sentences length = %d, after processed sentences num = %d " % (len(tokens), len(new_tokens))
    return new_tokens


def read_dataset(file_path, prompt_id, vocab, to_lower, score_index=6, char_level=False):
    """
       读取数据集文件，将文本和分数转换为模型的输入格式。

       参数：
       - file_path: 数据集文件的路径
       - prompt_id: 提示ID，用于筛选特定的作文集
       - vocab: 词汇表，用于将单词转换为索引
       - to_lower: 是否将文本转换为小写
       - score_index: 在数据文件中，分数位于第几列（默认是第6列）
       - char_level: 是否按字符级别处理文本（暂未实现）

       返回：
       - data_x: 转换为索引的文本数据
       - data_y: 对应的分数
       - prompt_ids: 对应的提示ID
       - max_sentlen: 文本中的最大句子长度
       - max_sentnum: 文本中的最大句子数
    """
    logger.info('Reading dataset from: ' + file_path)

    data_x, data_y, prompt_ids = [], [], []
    num_hit, unk_hit, total = 0., 0., 0.
    max_sentnum = -1
    max_sentlen = -1
    with codecs.open(file_path, mode='r', encoding='UTF8') as input_file:
        #input_file.next()
        #input_file.readline()
        for line in input_file:
            tokens = line.strip().split('\t')
            essay_id = int(tokens[0])
            essay_set = int(tokens[1])
            content = tokens[2].strip()
            score = float(tokens[score_index])
            if essay_set == prompt_id or prompt_id <= 0:
            #if  essay_set == prompt_id and score >=high_score[essay_set]:
                # tokenize text into sentences
                sent_tokens = text_tokenizer(content, replace_url_flag=True, tokenize_sent_flag=True)
                if to_lower:
                    sent_tokens = [[w.lower() for w in s] for s in sent_tokens]
                if char_level:
                    raise NotImplementedError
                sent_indices = []
                indices = []
                if char_level:
                    raise NotImplementedError
                else:
                    for sent in sent_tokens:
                        length = len(sent)
                        if max_sentlen < length:
                            max_sentlen = length
                        for word in sent:
                            if is_number(word):
                                indices.append(vocab['<num>'])
                                num_hit += 1
                            elif word in vocab:
                                indices.append(vocab[word])
                            else:
                                indices.append(vocab['<unk>'])
                                unk_hit += 1
                            total += 1
                        sent_indices.append(indices)
                        indices = []
                data_x.append(sent_indices)
                data_y.append(score)
                prompt_ids.append(essay_set)

                if max_sentnum < len(sent_indices):
                    max_sentnum = len(sent_indices)
    logger.info('  <num> hit rate: %.2f%%, <unk> hit rate: %.2f%%' % (100*num_hit/total, 100*unk_hit/total))
    return data_x, data_y, prompt_ids, max_sentlen, max_sentnum


def get_data(paths, prompt_id, vocab, tokenize_text=True, to_lower=True, sort_by_len=False,  score_index=6):
    """
        读取训练、验证和测试数据集，并获取最大句子长度和句子数。

        参数：
        - paths: 包含训练、验证和测试数据集的文件路径列表
        - prompt_id: 提示ID，用于筛选特定的作文集
        - vocab: 词汇表，用于将单词转换为索引
        - tokenize_text: 是否对文本进行标记化
        - to_lower: 是否将文本转换为小写
        - sort_by_len: 是否按句子长度排序
        - score_index: 在数据文件中，分数位于第几列（默认是第6列）

        返回：
        - 训练、验证和测试数据集的文本和分数，以及整体的最大句子长度和句子数
    """
    train_path, dev_path, test_path = paths[0], paths[1], paths[2]


    train_x, train_y, train_prompts, train_maxsentlen, train_maxsentnum = read_dataset(train_path, prompt_id, vocab, to_lower)
    dev_x, dev_y, dev_prompts, dev_maxsentlen, dev_maxsentnum = read_dataset(dev_path, prompt_id, vocab, to_lower)
    test_x, test_y, test_prompts, test_maxsentlen, test_maxsentnum = read_dataset(test_path, prompt_id, vocab,  to_lower)

    overal_maxlen = max(train_maxsentlen, dev_maxsentlen, test_maxsentlen)
    overal_maxnum = max(train_maxsentnum, dev_maxsentnum, test_maxsentnum)

    logger.info("Training data max sentence num = %s, max sentence length = %s" % (train_maxsentnum, train_maxsentlen))
    logger.info("Dev data max sentence num = %s, max sentence length = %s" % (dev_maxsentnum, dev_maxsentlen))
    logger.info("Test data max sentence num = %s, max sentence length = %s" % (test_maxsentnum, test_maxsentlen))
    logger.info("Overall max sentence num = %s, max sentence length = %s" % (overal_maxnum, overal_maxlen))

    return (train_x, train_y, train_prompts), (dev_x, dev_y, dev_prompts), (test_x, test_y, test_prompts),  overal_maxlen, overal_maxnum

def prompt(file_path, prompt,vocab):
    """
        获取指定提示ID的句子标记索引。

        参数：
        - file_path: 数据集文件的路径
        - prompt: 提示ID
        - vocab: 词汇表，用于将单词转换为索引

        返回：
        - 对应提示的句子标记索引列表
    """
    indices= []
    with codecs.open(file_path, mode='r', encoding='UTF8') as input_file:
        for line in input_file:
            tokens = line.strip().split('\t')
            prompt_id = int(tokens[0])
            content = tokens[1].strip()
            if prompt_id  == prompt:
                sent_tokens = text_tokenizer(content, replace_url_flag=True, tokenize_sent_flag=True)
                sent_tokens = [[w.lower() for w in s] for s in sent_tokens]
            for sent in sent_tokens:
                for word in sent:
                        if is_number(word):
                            indices.append(vocab['<num>'])
                        elif word in vocab:
                            indices.append(vocab[word])
                        else:
                            indices.append(vocab['<unk>'])
    return  indices

def prepare_sentence_data(datapaths, vocab,embedding_path=None, embedding='word2vec', embedd_dim=100, prompt_id=1, vocab_size=0, tokenize_text=True, \
                         to_lower=True, sort_by_len=False, score_index=6,prompt_in_traindata=True):
    """
        准备句子级别的数据集，包括读取数据、标记化、填充序列，以及构建嵌入矩阵。

        参数：
        - datapaths: 包含训练、验证和测试数据集的文件路径列表
        - vocab: 词汇表，用于将单词转换为索引
        - embedding_path: 嵌入矩阵的文件路径
        - embedding: 嵌入类型（默认使用word2vec）
        - embedd_dim: 嵌入向量的维度
        - prompt_id: 提示ID，用于筛选特定的作文集
        - vocab_size: 词汇表的大小
        - tokenize_text: 是否对文本进行标记化
        - to_lower: 是否将文本转换为小写
        - sort_by_len: 是否按句子长度排序
        - score_index: 在数据文件中，分数位于第几列（默认是第6列）
        - prompt_in_traindata: 是否在训练数据中包含提示信息

        返回：
        - 训练、验证和测试数据集的文本、分数、掩码、提示ID，以及嵌入矩阵、最大句子长度、最大句子数和训练集的平均分数
    """
    assert len(datapaths) == 3, "data paths should include train, dev and test path"
    (train_x, train_y, train_prompts), (dev_x, dev_y, dev_prompts), (test_x, test_y, test_prompts), overal_maxlen, overal_maxnum = \
        get_data(datapaths, prompt_id, vocab, tokenize_text=True, to_lower=True, sort_by_len=False,  score_index=6)

    X_train, y_train, mask_train = utils.padding_sentence_sequences(train_x, train_y, overal_maxnum, overal_maxlen, post_padding=True)
    X_dev, y_dev, mask_dev = utils.padding_sentence_sequences(dev_x, dev_y, overal_maxnum, overal_maxlen, post_padding=True)
    X_test, y_test, mask_test = utils.padding_sentence_sequences(test_x, test_y, overal_maxnum, overal_maxlen, post_padding=True)

    if prompt_id:
        train_pmt = np.array(train_prompts, dtype='int32')
        dev_pmt = np.array(dev_prompts, dtype='int32')
        test_pmt = np.array(test_prompts, dtype='int32')

    train_mean = y_train.mean(axis=0)
    train_std = y_train.std(axis=0)
    dev_mean = y_dev.mean(axis=0)
    dev_std = y_dev.std(axis=0)
    test_mean = y_test.mean(axis=0)
    test_std = y_test.std(axis=0)


    # We need the dev and test sets in the original scale for evaluation
    # dev_y_org = y_dev.astype(reader.get_ref_dtype())
    # test_y_org = y_test.astype(reader.get_ref_dtype())

    # Convert scores to boundary of [0 1] for training and evaluation (loss calculation)
    Y_train = get_model_friendly_scores(y_train, train_prompts)
    Y_dev = np.array(y_dev)
    Y_test = np.array(y_test)
    #Y_dev = get_model_friendly_scores(y_dev, dev_prompts)
    #Y_test = get_model_friendly_scores(y_test, test_prompts)
    scaled_train_mean = Y_train.mean(axis=0)
    # print Y_train.shape

    logger.info('Statistics:')

    logger.info('  train X shape: ' + str(X_train.shape))
    logger.info('  dev X shape:   ' + str(X_dev.shape))
    logger.info('  test X shape:  ' + str(X_test.shape))

    logger.info('  train Y shape: ' + str(Y_train.shape))
    logger.info('  dev Y shape:   ' + str(Y_dev.shape))
    logger.info('  test Y shape:  ' + str(Y_test.shape))

    logger.info('  train_y mean: %s, stdev: %s, train_y mean after scaling: %s' %
                (str(train_mean), str(train_std), str(scaled_train_mean)))

    if embedding_path:
        embedd_dict, embedd_dim, _ = utils.load_word_embedding_dict(embedding, embedding_path, vocab, logger, embedd_dim)
        embedd_matrix = utils.build_embedd_table(vocab, embedd_dict, embedd_dim, logger, caseless=True)
    else:
        embedd_matrix = None

    return (X_train, Y_train, mask_train,train_prompts), (X_dev, Y_dev, mask_dev,dev_prompts), (X_test, Y_test, mask_test,test_prompts), \
            embedd_matrix, overal_maxlen, overal_maxnum, scaled_train_mean
