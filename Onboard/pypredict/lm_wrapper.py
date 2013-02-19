#!/usr/bin/python3

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# Author: marmuta <marmvta@gmail.com>
#

from __future__ import division, print_function, unicode_literals

import sys
import re
import codecs
from math import log
import unicodedata

import pypredict.lm as lm
from pypredict.lm import overlay, linint, loglinint


class _BaseModel:

    def learn_tokens(self, tokens, allow_new_words=True):
        """ Extract n-grams from tokens and count them. """
        for ngram in self._extract_ngrams(tokens):
            self.count_ngram(ngram, allow_new_words)

    def _extract_ngrams(self, tokens):
        """
        Extract n-grams from tokens.

        Doctests:
        >>> m = DynamicModel(3)
        >>> list(m._extract_ngrams(["word1", "word2", "<unk>", "word3"]))
        [['word1'], ['word1', 'word2'], ['word2'], ['word3']]
        >>> list(m._extract_ngrams(["word1", "word2", "<s>", "word3"]))
        [['word1'], ['word1', 'word2'], ['word2'], ['<s>'], ['<s>', 'word3'], ['word3']]
        """
        token_sections = []
        # Don't let <unk> enter the model.
        # Split the token stream into sections between <unk>s.
        unk_sections = split_tokens(tokens, "<unk>")
        for section in unk_sections:
            # Don't learn across sentence marks.
            token_sections.extend(split_tokens(section, "<s>", True))

        # Run a window of size <order> along the section and return n-grams.
        for token_section in token_sections:
            section = token_section

            for i,token in enumerate(section):
                for n in range(self.order):
                    if i+n+1 <= len(section):
                        ngram = section[i:i+n+1]
                        assert(n == len(ngram)-1)
                        yield ngram

    def get_counts(self):
        """
        Return number of n-gram types and total occurances
        for each n-gram level.
        """
        counts = [0]*self.order
        totals = [0]*self.order
        for ng in self.iter_ngrams():
            counts[len(ng[0])-1] +=  1
            totals[len(ng[0])-1] += ng[1]
        return counts, totals

    def prune(self, prune_count):
        """
        Return a copy of self with all ngrams removed whose
        count is less or equal to <prune_count>.
        """
        model = self.__class__(self.order)
        model.smoothing = self.smoothing

        for it in self.iter_ngrams():
            ngram = it[0]
            count = it[1]
            if count > prune_count:
                model.count_ngram(ngram, count)

        return model


class LanguageModel(lm.LanguageModel, _BaseModel):
    """ Keep this to access the class constants. """
    def __init__(self):
        raise NotImplementedError()

class DynamicModel(lm.DynamicModel, _BaseModel):
    pass


class DynamicModelKN(lm.DynamicModelKN, _BaseModel):
    pass


class CachedDynamicModel(lm.CachedDynamicModel, _BaseModel):
    pass


def split_tokens(tokens, separator, keep_separator = False):
    """
    Doctests:
    # excluding separator
    >>> split_tokens(["<unk>", "word1", "word2", "word3"], "<unk>")
    [['word1', 'word2', 'word3']]
    >>> split_tokens(["word1", "<unk>", "word2", "word3"], "<unk>")
    [['word1'], ['word2', 'word3']]
    >>> split_tokens(["word1", "word2", "word3", "<unk>"], "<unk>")
    [['word1', 'word2', 'word3']]

    # including separator
    >>> split_tokens(["<unk>", "word1", "word2", "word3"], "<unk>", True)
    [['<unk>', 'word1', 'word2', 'word3']]
    >>> split_tokens(["word1", "<unk>", "word2", "word3"], "<unk>", True)
    [['word1'], ['<unk>', 'word2', 'word3']]
    >>> split_tokens(["word1", "word2", "word3", "<unk>"], "<unk>", True)
    [['word1', 'word2', 'word3']]
    """
    token_sections = []
    token_section = []
    for token in tokens:
        if token == separator:
            if token_section:
                token_sections.append(token_section)

            if keep_separator:
                token_section = [separator]
            else:
                token_section = []
        else:
            token_section.append(token)

    if len(token_section) > 1 or \
       (token_section and token_section[0] != separator):
        token_sections.append(token_section)

    return token_sections

def split_sentences(text, disambiguate=False):
    """ Split text into sentences. """

    # Remove carriage returns from Moby Dick.
    # Don't change the text's length, keep it in sync with spans.
    filtered = text.replace("\r"," ")


    # split into sentence fragments
    matches = re.finditer("""  .*?
                                 (?:
                                   [.;:!?](?:(?=[\s])|\") # punctuation
                                   | \s*\\n\s*\\n         # double newline
                                   | <s>                  # sentence end mark
                                 )
                             | .+$                    # last sentence fragment
                          """, filtered, re.UNICODE|re.DOTALL|re.VERBOSE)

    # filter matches
    sentences = []
    spans = []
    for match in matches:
        sentence = match.group()
        # not only newlines? remove fragments with only double newlines
        if not re.match("^\s*\n+\s*$", sentence, re.UNICODE):
            begin = match.start()
            end   = match.end()

            # strip whitespace including newlines
            l = len(sentence)
            sentence = sentence.lstrip()
            begin += l - len(sentence)

            l = len(sentence)
            sentence = sentence.rstrip()
            end -= l - len(sentence)

            # remove <s>
            sentence = re.sub("<s>", "   ", sentence)

            # remove newlines and double spaces - no, invalidates spans
            #sentence = re.sub(u"\s+", u" ", sentence)

            # strip whitespace from the cuts, remove carriage returns
            l = len(sentence)
            sentence = sentence.rstrip()
            end -= l - len(sentence)
            l = len(sentence)
            sentence = sentence.lstrip()
            begin += l - len(sentence)

            # add <s> sentence separators if the end of the sentence is
            # ambiguous - required by the split_corpus tool where the
            # result of split_sentences is saved to a text file and later
            # fed back to split_sentences again.
            if disambiguate:
                if not re.search("[.;:!?]\"?$", sentence, re.UNICODE):
                    sentence += " <s>"

            sentences.append(sentence)
            spans.append([begin, end])

    return sentences, spans

def tokenize_sentence(sentence):

    iterator = re.finditer("""
    (                                     # <unk>
      (?:^|(?<=\s))
        \S*(\S)\\2{3,}\S*                 # char repeated more than 3 times
      (?=\s|$)
    ) |
    (                                     # <num>
      (?:[-+]?\d+(?:[.,]\d+)*)            # anything numeric looking
      | (?:[.,]\d+)
    ) |
    (                                     # word
      (?:[-]{0,2}                         # allow command line options
        [^\W\d]\w*(?:[-'][\w]+)*[']?)     # word, not starting with a digit
      | <unk> | <s> | </s> | <num>        # pass through control words
      | <bot:[a-z]*>                      # pass through begin of text merkers
      | (?:^|(?<=\s))
          (?:
            \|                            # common space delimited operators
          )
        (?=\s|$)
    )
    """, sentence, re.UNICODE|re.DOTALL|re.VERBOSE)

    tokens = []
    spans = []

    for match in iterator:
        groups = match.groups()
        if groups[3]:
            tokens.append(groups[3])
            spans.append(match.span())
        elif groups[2]:
            tokens.append("<num>")
            spans.append(match.span())
        elif groups[0]:
            tokens.append("<unk>")
            spans.append(match.span())

    return tokens, spans

def tokenize_text(text):
    """ Split text into word tokens.
        The result is ready for use in learn_tokens().

        Sentence begins, if detected, are marked with "<s>".
        Numbers are replaced with the number marker <num>.
        Other tokens that could confuse the prediction are
        replaced with the unknown word marker "<unk>".

        Examples, text -> tokens:
            "We saw whales"  -> ["We", "saw", "whales"]
            "We saw whales " -> ["We", "saw", "whales"]
            "Hello there! We saw 5 whales "
                             -> ["Hello", "there", "<s>",
                                 "We", "saw", "<num>", "whales"]
    """

    tokens = []
    spans = []
    sentences, sentence_spans = split_sentences(text)
    for i,sentence in enumerate(sentences):
        ts, ss = tokenize_sentence(sentence)

        sbegin = sentence_spans[i][0]
        ss = [[s[0]+sbegin, s[1]+sbegin] for s in ss]

        # sentence begin?
        if i > 0:
            tokens.append("<s>")      # prepend sentence begin marker
            spans.append([sbegin, sbegin]) # empty span
        tokens.extend(ts)
        spans.extend(ss)

    return tokens, spans

def tokenize_context(text):
    """ Split text into word tokens + prefix.
        The result is ready for use in predict().
    """
    tokens, spans = tokenize_text(text)
    if not re.match("""
                  ^$                              # empty string
                | .*[-'\w]$                       # word at the end
                | (?:^|.*\s)[\+\-\*/=\<>&\^|]=?$  # operator, equal sign
                | .*(\S)\\1{3,}$                  # anything repeated > 3 times
                """, text, re.UNICODE|re.DOTALL|re.VERBOSE):
        tokens += [""]
    return tokens

def read_corpus(filename, encoding=None):
    """ Read corpus, encoding may be 'utf-8', 'latin-1'. """

    if encoding:
        encodings = [encoding]
    else:
        encodings = ['utf-8', 'latin-1']

    for i,enc in enumerate(encodings):
        try:
            text = codecs.open(filename, encoding=enc).read()
        except UnicodeDecodeError as err:
            #print err
            if i == len(encodings)-1: # all encodings failed?
                raise err
            continue   # silently retry with the next encoding
        break

    return text

def read_vocabulary(filename, encoding=None):
    """
    Read vocabulary with one word per line.
    Encoding may be 'utf-8', 'latin-1', like read_corpus.
    """
    text = read_corpus(filename, encoding)
    vocabulary = text.split("\n")

    for ctrl_word in ["<unk>", "<s>", "</s>", "</num>"]:
        if not ctrl_word in vocabulary:
            vocabulary.append(ctrl_word)

    return vocabulary


def extract_vocabulary(tokens, min_count=1, max_words=0):
    """ Extract the most frequent <max_words> words from <tokens>. """
    m = {}
    for t in tokens:
        m[t] = m.get(t, 0) + 1
    items = [x for x in list(m.items()) if x[1] >= min_count]
    items = sorted(items, key=lambda x: x[1], reverse=True)
    if max_words:
        return items[:max_words]
    else:
        return items

def filter_tokens(tokens, vocabulary):
    v = set(vocabulary)
    return [t if t in v else "<unk>" for t in tokens]

def entropy(model, tokens, order=None):

    if not order:
        order = model.order  # fails for non-ngram models, specify order manually

    ngram_count = 0
    entropy = 0
    word_count = len(tokens)

    # extract n-grams of maximum length
    for i in range(len(tokens)):
        b = max(i-(order-1),0)
        e = min(i-(order-1)+order, len(tokens))
        ngram = tokens[b:e]
        if len(ngram) != 1:
            p = model.get_probability(ngram)
            if p == 0:
                print(word_count, ngram,p)
            e = log(p, 2) if p else float("infinity")
            entropy += e
            ngram_count += 1

    entropy = -entropy/word_count if word_count else 0
    try:
        perplexity = 2 ** entropy
    except:
        perplexity = 0

    return entropy, perplexity


def ksr(query_model, learn_model, sentences, limit, progress=None):
    """ Calculate keystroke savings rate from simulated typing. """
    total_chars, pressed_keys = simulate_typing(query_model, learn_model, sentences, limit, progress)
    saved_keystrokes = total_chars - pressed_keys
    return saved_keystrokes * 100.0 / total_chars if total_chars else 0

def simulate_typing(query_model, learn_model, sentences, limit, progress=None):

    total_chars = 0
    pressed_keys = 0

    for i,sentence in enumerate(sentences):
        inputline = ""

        cursor = 0
        while cursor < len(sentence):
            context = tokenize_context(". " + inputline) # simulate sentence begin
            prefix = context[len(context)-1] if context else ""
            prefix_to_end = sentence[len(inputline)-len(prefix):]
            target_word = re.search("^([\w]|[-'])*", prefix_to_end, re.UNICODE).group()
            choices = query_model.predict(context, limit)

            if 0:  # step mode for debugging
                print("cursor=%d total_chars=%d pressed_keys=%d" % (cursor, total_chars, pressed_keys))
                print("sentence= '%s'" % sentence)
                print("inputline='%s'" % inputline)
                print("prefix='%s'" % prefix)
                print("prefix_to_end='%s'" % prefix_to_end)
                print("target_word='%s'" % (target_word))
                print("context=", context)
                print("choices=", choices)
                input()

            if target_word in choices:
                added_chars = len(target_word) - len(prefix)
                if added_chars == 0: # still right after insertion point?
                    added_chars = 1  # continue with next character
            else:
                added_chars = 1

            for k in range(added_chars):
                inputline += sentence[cursor]
                cursor += 1
                total_chars += 1

            pressed_keys += 1

        # learn the sentence
        if learn_model:
            tokens = tokenize_context(sentence)
            learn_model.learn_tokens(tokens)

        # progress feedback
        if progress:
            progress(i, len(sentences), total_chars, pressed_keys)

    return total_chars, pressed_keys


from contextlib import contextmanager

@contextmanager
def timeit(s, out=sys.stdout):
    import time, gc

    if out:
        gc.collect()
        gc.collect()
        gc.collect()

        t = time.time()
        text = s if s else "timeit"
        out.write("%-15s " % text)
        out.flush()
        yield None
        out.write("%10.3fms\n" % ((time.time() - t)*1000))
    else:
        yield None




if __name__ == '__main__':
    a = [".", ". ", " . ", "a. ", "a. b"]
    for text in a:
        print("split_sentences('%s'): %s" % (text, repr(split_sentences(text))))

    for text in a:
        print("tokenize_text('%s'): %s" % (text, repr(tokenize_text(text))))

    for text in a:
        print("tokenize_context('%s'): %s" % (text, repr(tokenize_context(text))))


