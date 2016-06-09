from contextlib import contextmanager
from pyparsing import alphas, alphanums, nums, CaselessKeyword, Group, Optional, ZeroOrMore, Word, Literal, ParseException, ParserElement, restOfLine, QuotedString, Forward, CharsNotIn, OneOrMore, originalTextFor  # type: ignore
from typing import MutableMapping, List  # flake8: noqa
from . import input as i
from . import output as o
import re

__all__ = [
    'parse_input_spec',
    'parse_output_spec',
    'parse_spec',
    'parse_embedded_spec',
    'parse_answer_set',
]


@contextmanager
def PyParsingDefaultWhitespaceChars(whitespace_chars):
    '''Set the given whitespace_chars as pyparsing's default whitespace chars while the context manager is active.

    Since ParserElement.DEFAULT_WHITE_CHARS is a global variable, this method is not thread-safe (but no pyparsing parser construction is thread-safe for the same reason anyway).
    '''
    # A possible solution to this problem:
    # Since the pyparsing code is basically a single big file, we could just copy it (under dlvhex/vendor or something like that) and have our own "private" version of pyparsing. (TODO: think about this some more and maybe do it)
    previous_whitespace_chars = ParserElement.DEFAULT_WHITE_CHARS
    ParserElement.setDefaultWhitespaceChars(whitespace_chars)
    yield
    ParserElement.setDefaultWhitespaceChars(previous_whitespace_chars)


DEFAULT_WHITESPACE_CHARS = ' \n\t\r'  # this is the same as pyparsing's default


def ignore_comments(parser):
    '''Ignore comments (starting with '%' and continuing until the end of the same line) on the given parser (ParserElement instance).'''
    comment = '%' + restOfLine
    parser.ignore(comment)
    return parser


# Common syntax elements
with PyParsingDefaultWhitespaceChars(DEFAULT_WHITESPACE_CHARS):
    predicate_name = Word(alphas, alphanums + '_').setName('predicate name')  # TODO: which chars does dlvhex allow here?
    py_identifier = Word(alphas + '_', alphanums + '_').setName('python identifier')
    py_qualified_identifier = Word(alphas + '_', alphanums + '_.').setName('qualified python identifier')
    var = Word(alphas, alphanums).setName('variable')
    integer = Word(nums).setName('integer').setParseAction(lambda t: int(t[0]))
    INPUT = CaselessKeyword('INPUT').suppress()
    FOR = CaselessKeyword('for').suppress()
    IN = CaselessKeyword('in').suppress()
    OUTPUT = CaselessKeyword('OUTPUT').suppress()
    PREDICATE = CaselessKeyword('predicate').suppress()
    CONTAINER = CaselessKeyword('container').suppress()
    SET = CaselessKeyword('set').suppress()
    SEQUENCE = CaselessKeyword('sequence').suppress()
    MAPPING = CaselessKeyword('mapping').suppress()
    INDEX = CaselessKeyword('index').suppress()
    KEY = CaselessKeyword('key').suppress()
    CONTENT = CaselessKeyword('content').suppress()
    CLASS = CaselessKeyword('class').suppress()
    ARGUMENTS = CaselessKeyword('arguments').suppress()
    lpar = Literal('(').suppress()
    rpar = Literal(')').suppress()
    lbracket = Literal('[').suppress()
    rbracket = Literal(']').suppress()
    lbrace = Literal('{').suppress()
    rbrace = Literal('}').suppress()
    dot = Literal('.').suppress()
    comma = Literal(',').suppress()
    colon = Literal(':').suppress()
    semicolon = Literal(';').suppress()
    equals = Literal('=').suppress()
    amp = Literal('&').suppress()


def RawInputSpecParser():
    '''Syntax of the INPUT statement (and nothing else).'''
    with PyParsingDefaultWhitespaceChars(DEFAULT_WHITESPACE_CHARS):
        # Accessing objects, some examples:
        # - just access a variable directly:            node
        # - access a field on a variable:               node.label
        # - accessing a fixed index in a collection:    some_tuple[3]
        # - chainable:                                  node.neighbors[2].label
        field_accessor = dot + py_identifier
        index_accessor = lbracket + integer + rbracket
        accessor = var('var') + Group(ZeroOrMore(field_accessor | index_accessor))('path')
        #
        accessor.setParseAction(lambda t: i.InputAccessor(t.var, t.path))

        # Iterating over objects, some examples:
        # - iterate over elements:                          for node in nodes
        # - iterate over indices and elements of a list:    for (i, m) in node.neighbors
        # - iterate over keys and elements of a dictionary: for (k, v) in some_dict
        iteration_element = var('elem')
        iteration_assoc_and_element = lpar + var('assoc') + comma + var('elem') + rpar
        set_iteration = FOR + iteration_element + IN + Optional(SET) + accessor('accessor')     # TODO: Ambiguity? Is "set" the SET keyword or a variable named "set"? (should be unambiguous since we can look at the following token? variable could be named "for" too). We could just forbid variable names that are keywords.
        sequence_iteration = FOR + iteration_assoc_and_element + IN + SEQUENCE + accessor('accessor')
        mapping_iteration = FOR + iteration_assoc_and_element + IN + MAPPING + accessor('accessor')
        iteration = sequence_iteration | mapping_iteration | set_iteration
        iterations = Group(ZeroOrMore(iteration))
        #
        set_iteration.setParseAction(lambda t: i.InputSetIteration(t.elem, t.accessor))
        sequence_iteration.setParseAction(lambda t: i.InputSequenceIteration(t.assoc, t.elem, t.accessor))
        mapping_iteration.setParseAction(lambda t: i.InputMappingIteration(t.assoc, t.elem, t.accessor))
        # Note: t.get(n) returns None if n doesn't exist while t.n would return an empty string

        predicate_args = Group(Optional(accessor + ZeroOrMore(comma + accessor) + Optional(comma)))
        predicate_spec = predicate_name('pred') + lpar + predicate_args('args') + rpar + iterations('iters') + semicolon
        predicate_specs = Group(ZeroOrMore(predicate_spec))
        #
        predicate_spec.setParseAction(lambda t: i.InputPredicate(t.pred, t.args, t.iters))

        # TODO: Types? yes or no?
        input_arg = var
        input_args = Group(Optional(input_arg + ZeroOrMore(comma + input_arg) + Optional(comma)))

        input_statement = INPUT + lpar + input_args('args') + rpar + lbrace + predicate_specs('preds') + rbrace
        #
        input_statement.setParseAction(lambda t: i.InputSpecification(t.args, t.preds))
        return input_statement


def InputSpecParser():
    '''Syntax of the INPUT statement (supports comments starting with '%').'''
    with PyParsingDefaultWhitespaceChars(DEFAULT_WHITESPACE_CHARS):
        return ignore_comments(RawInputSpecParser())


def RawOutputSpecParser():
    '''Syntax of the OUTPUT statement (and nothing else).'''
    with PyParsingDefaultWhitespaceChars(DEFAULT_WHITESPACE_CHARS):
        literal = integer | QuotedString('"', escChar='\\')
        literal.setParseAction(lambda t: o.Literal(t[0]))  # not strictly necessary to wrap this, but it simplifies working with the syntax tree

        asp_variable = Word(alphas)  # TODO: Must start with upper case?
        asp_variable.setParseAction(lambda t: o.Variable(t[0]))  # to distinguish variable names from literal string values

        # TODO:
        # Instead of explicitly marking references with '&', we might just define a convention as follows:
        #   * Output names start with lowercase characters
        #   * ASP variables start with uppercase characters (as they do in actual ASP code)
        reference = amp + py_identifier
        reference.setParseAction(lambda t: o.Reference(t[0]))  # to distinguish from literal string values

        asp_query = originalTextFor(OneOrMore(QuotedString('"', escChar='\\') | CharsNotIn(';', exact=1)))  # TODO: We should parse this, to extract variable names etc.

        expr = Forward()

        # TODO: Instead of semicolon, we could use (semicolon | FollowedBy(rbrace)) to make the last semicolon optional (but how would that work with asp_query...)
        predicate_clause = PREDICATE + colon + asp_query('predicate') + semicolon
        content_clause = CONTENT + colon + expr('content') + semicolon
        index_clause = INDEX + colon + asp_variable('index') + semicolon
        key_clause = KEY + colon + expr('key') + semicolon
        #
        simple_set_spec = SET + lbrace + predicate_name('predicate') + rbrace
        set_spec = SET + lbrace + (predicate_clause & content_clause) + rbrace
        sequence_spec = SEQUENCE + lbrace + (predicate_clause & content_clause & index_clause) + rbrace
        mapping_spec = MAPPING + lbrace + (predicate_clause & content_clause & key_clause) + rbrace
        expr_collection = set_spec | simple_set_spec | sequence_spec | mapping_spec
        #
        simple_set_spec.setParseAction(lambda t: o.ExprSimpleSet(t.predicate))
        set_spec.setParseAction(lambda t: o.ExprSet(t.predicate, t.content))
        sequence_spec.setParseAction(lambda t: o.ExprSequence(t.predicate, t.content, t.index))
        mapping_spec.setParseAction(lambda t: o.ExprMapping(t.predicate, t.content, t.key))

        expr_obj_args = Group(Optional(expr + ZeroOrMore(comma + expr) + Optional(comma)))
        expr_obj = Optional(py_qualified_identifier, default=None)('constructor') + lpar + expr_obj_args('args') + rpar
        #
        expr_obj.setParseAction(lambda t: o.ExprObject(t.constructor, t.args))

        expr << (literal | expr_collection | expr_obj | reference | asp_variable)

        named_output_spec = py_identifier('name') + equals + expr('expr')
        output_statement = OUTPUT + lbrace + Optional(named_output_spec + ZeroOrMore(comma + named_output_spec) + Optional(comma)) + rbrace
        #
        named_output_spec.setParseAction(lambda t: (t.name, t.expr))
        output_statement.setParseAction(lambda t: o.OutputSpecification(t))
        return output_statement


def OutputSpecParser():
    '''Syntax of the OUTPUT statement (supports comments starting with '%').'''
    with PyParsingDefaultWhitespaceChars(DEFAULT_WHITESPACE_CHARS):
        return ignore_comments(RawOutputSpecParser())


def RawSpecParser():
    '''Syntax of the whole I/O mapping specification: One INPUT statement and one OUTPUT statement in any order. This parser does not support comments.'''
    with PyParsingDefaultWhitespaceChars(DEFAULT_WHITESPACE_CHARS):
        i = RawInputSpecParser().setResultsName('input')
        o = RawOutputSpecParser().setResultsName('output')
        p = Optional(i) & Optional(o)
        # collect input and output
        p.setParseAction(lambda t: (t.get('input'), t.get('output')))  # TODO
        return p


def SpecParser():
    '''Syntax of the whole I/O mapping specification: One INPUT statement and one OUTPUT statement in any order. This parser supports comments starting with '%'.'''
    with PyParsingDefaultWhitespaceChars(DEFAULT_WHITESPACE_CHARS):
        return ignore_comments(RawOutputSpecParser())


class EmbeddedSpecParser:
    """Syntax of the whole I/O mapping specification, embedded in ASP comments starting with '%!'."""
    # I tried doing this part with pyparsing too, so the whole parsing can be performed in a single pass without an intermediate string representation.
    # However, I was not able to make it work yet, so I am using a simple regex-based implementation at the moment.
    # Most likely problem with the pyparsing attempt: automatic handling of whitespace combined with LineStart() and LineEnd()
    # See also: http://pyparsing.wikispaces.com/share/view/18478063
    # The old attempt:
    #     p = SpecParser()
    #     asp_quoted_string = QuotedString('"', escChar='\\')
    #     asp_end = LineEnd() | '%!' | ('%' + ZeroOrMore(CharsNotIn('\n')) + LineEnd())       # '%!' must be before the regular comments since the '|' operator matches the first subexpression (MatchFirst)
    #     asp_line = LineStart() + ZeroOrMore(CharsNotIn('"%') | asp_quoted_string) + asp_end
    #     p.ignore(asp_line)
    #     return p
    #
    # This seems to work better, although neither LineStart() nor LineEnd() will match if the line starts with whitespace
    # (presumably because the parser by default skips as much whitespace as possible after parsing a token):
    #    asp_quoted_string = QuotedString('"', escChar='\\')
    #    asp_end = LineEnd().leaveWhitespace() | '%!' | ('%' + ZeroOrMore(CharsNotIn('\n')) + LineEnd().leaveWhitespace())       # '%!' must be before the regular comments since the '|' operator matches the first subexpression (MatchFirst)
    #    asp_line = (LineStart().leaveWhitespace() | LineEnd().leaveWhitespace()) + ZeroOrMore(CharsNotIn('"%\n') | asp_quoted_string) + asp_end
    #    p.ignore(asp_line)
    #
    # This seems to work quite well (implementation of comments inside %! part is still missing though, would be an ignore on SpecParser()):
    #    ParserElement.setDefaultWhitespaceChars(' \t\r')
    #    p = ZeroOrMore(Word(printables))
    #    # p.setWhitespaceChars(' \t\r')  # TODO: What to do with '\r'?
    #    linebreak = White('\n')
    #    asp_quoted_string = QuotedString('"', escChar='\\')
    #    asp_end = FollowedBy(linebreak) | '%!' | ('%' + ZeroOrMore(CharsNotIn('\n')) + FollowedBy(linebreak))       # '%!' must be before the regular comments since the '|' operator matches the first subexpression (MatchFirst)
    #    asp_line = (linebreak | StringStart()) + ZeroOrMore(CharsNotIn('"%\n') | asp_quoted_string) + asp_end
    #    p.ignore(asp_line)
    #    p.ignore(linebreak)

    spec_parser = RawSpecParser()

    # TODO:
    # A reasonable simplification might be to only allow %! comments for input specification at the start of a line,
    # i.e. only some whitespace may be before %! comments, and no ASP code.
    embedded_re = re.compile(r'''
        ^  # Start of each line (in MULTILINE mode)
        # The ASP part before comments
        (?:
            [^\n%"]  # anything except newlines, comment start, and quotes
            |
            # Quoted string: any char except newlines/backslash/quotes, or backslash escape sequences
            " (?: [^\n\\"] | \\. )* "
        )*
        %\!                     # Our specification language is embedded in special %! comments
        (?P<spec> [^\n%]* )     # The part we want to extract
        (?: %.* )?              # Comments in the specification language also start with % (like regular ASP comments)
        $  # end of each line (in MULTILINE mode)
    ''', re.MULTILINE | re.VERBOSE)

    @classmethod
    def extractFromString(cls, string):
        return '\n'.join(m.group('spec') for m in cls.embedded_re.finditer(string))

    def parseString(self, string, *, parseAll=True):
        return (_parse(type(self).spec_parser, type(self).extractFromString(string)),)


def AnswerSetParser():
    '''Parse the answer set from a single line of dlvhex' output.'''
    with PyParsingDefaultWhitespaceChars(DEFAULT_WHITESPACE_CHARS):
        quoted_string = QuotedString(quoteChar='"', escChar='\\')
        constant_symbol = Word(alphas, alphanums + '_')  # TODO: Check what dlvhex2 allows here (probably need at add underscores at least?)
        arg = integer | quoted_string | constant_symbol
        fact = predicate_name('pred') + Group(Optional(lpar + arg + ZeroOrMore(comma + arg) + rpar))('args')
        answer_set = lbrace + Optional(fact + ZeroOrMore(comma + fact)) + rbrace  # + LineEnd()
        #
        fact.setParseAction(lambda t: (t.pred, tuple(t.args)))

        def collect_facts(t) -> o.AnswerSet:
            d = {}  # type: MutableMapping[str, List[o.FactArgumentTuple]]
            for (pred, args) in t:
                if pred not in d:
                    d[pred] = [args]
                    # Note:
                    # Technically we should use a set instead of a list here,
                    # but dlvhex2 already performs the deduplication for us
                    # so there is no need to check for collisions again.
                    #
                    # One problem:
                    # dlvhex2 seems to consider abc and "abc" (quoted/non-quoted) different,
                    # but on the python side it is represented by the same string 'abc'.
                else:
                    d[pred].append(args)
            return d  # type: ignore
        answer_set.setParseAction(collect_facts)
        return answer_set


def _parse(parser, string):
    try:
        result = parser.parseString(string, parseAll=True)
        return result[0]
    except ParseException:
        # rethrow
        raise
    # except:
    #     pass  # TODO


class LazyInit:
    def __init__(self, constructor):
        self._lazy_constructor = constructor
        self._lazy_obj = None

    @property
    def lazy_obj(self):
        if self._lazy_obj is None:
            self._lazy_obj = self._lazy_constructor()
        return self._lazy_obj

    def __getattr__(self, name):
        return getattr(self.lazy_obj, name)


input_spec_parser = LazyInit(InputSpecParser)
output_spec_parser = LazyInit(OutputSpecParser)
spec_parser = LazyInit(SpecParser)
embedded_spec_parser = LazyInit(EmbeddedSpecParser)
answer_set_parser = LazyInit(AnswerSetParser)


def parse_input_spec(string):
    return _parse(input_spec_parser, string)


def parse_output_spec(string):
    return _parse(output_spec_parser, string)


def parse_spec(string):
    return _parse(spec_parser, string)


def parse_embedded_spec(string):
    return _parse(embedded_spec_parser, string)


def parse_answer_set(string: str) -> o.AnswerSet:
    return _parse(answer_set_parser, string)
