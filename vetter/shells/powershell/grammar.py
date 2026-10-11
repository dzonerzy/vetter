"""PowerShell's grammar (Windows PowerShell 5.1), made when this module is
imported: a template whose keywords and operators are made
case-insensitive, as fold() compares them (`ıf` is if).

    GRAMMAR    # zgram's text
"""

import re

# Keywords that start a statement (a command can't be named so); `catch`,
# `else`, `in`, `until`, `param` alone and the like are commands' names
STATEMENT_KEYWORDS = ["if", "switch", "foreach", "for", "while", "do", "function", "filter", "workflow",
                      "return", "throw", "exit", "break", "continue", "trap", "try", "begin", "process", "end",
                      "dynamicparam", "data", "class", "enum", "using", "configuration"]
KEYWORDS = STATEMENT_KEYWORDS + ["elseif", "else", "until", "catch", "finally", "param", "in"]

# Binary operators (with their c and i forms where they compare)
_COMPARING = ["eq", "ne", "gt", "ge", "lt", "le", "like", "notlike", "match", "notmatch", "replace", "contains",
              "notcontains", "in", "notin", "split"]
BINARY_OPERATORS = (_COMPARING + ["c" + o for o in _COMPARING] + ["i" + o for o in _COMPARING]
                    + ["is", "isnot", "as", "and", "or", "xor", "band", "bor", "bxor", "shl", "shr", "join", "f"])

# (the letters outside ASCII whose uppercase is i and s: fold()'s, in UTF-8)
_FOLDED_IN = {"i": "'\\xc4\\xb1'", "s": "'\\xc5\\xbf'"}


def _ci(word):
    """A case-insensitive literal (as fold() compares: `ıf` is if)."""
    def letter(c):
        if not c.isalpha():
            return f"'{c}'"
        if c.lower() in _FOLDED_IN:
            return f"([{c.lower()}{c.upper()}] | {_FOLDED_IN[c.lower()]})"
        return f"[{c.lower()}{c.upper()}]"
    return " ".join(letter(c) for c in word)


GRAMMAR_TEMPLATE = r"""
script        = statements

# Statements: a newline or ; between them; after one ending in } (if,
# foreach, function...), the next may follow right away
statements    = lb (statement? (term lb statement?)*) lb
@silent term  = sp comment? (nl | ';')
statement     = compound (sp &statement_start statement)?
              | flow_stmt | param_block | pipeline
@silent statement_start = [^ \t\r\n;)}}#]
@silent compound = labeled | if_stmt | while_stmt | do_stmt | for_stmt | foreach_stmt | switch_stmt
                 | try_stmt | trap_stmt | function_def | named_block | data_stmt
labeled       = ':' name sp (while_stmt | do_stmt | for_stmt | foreach_stmt | switch_stmt)
if_stmt       = {if} kw sp cond lb block (lb {elseif} kw sp cond lb block)* (lb {else} kw lb block)?
@silent cond  = '(' lb pipeline lb ')'
while_stmt    = {while} kw sp cond lb block
do_stmt       = {do} kw lb block lb ({while} | {until}) kw sp cond
# (every part of the header can be left out: for(){})
for_stmt      = {for} kw sp '(' lb pipeline? (for_sep pipeline?)? (for_sep pipeline?)? lb ')' lb block
@silent for_sep = sp (';' | nl) lb
# (`in` then a blank or `(`: `in$x` is one word)
foreach_stmt  = {foreach} kw sp (dash {parallel} kw sp)? '(' lb variable sp {in} &([ \t\r\n(] | '`')
                lb pipeline lb ')' lb block
switch_stmt   = {switch} kw (sp dash word_name !(sp? ':'))* sp ((dash {file} kw sp argument) | cond) lb
                '{{' lb (switch_clause (term? lb switch_clause)*)? term? lb '}}'
switch_clause = (argument | expression) lb block
# (a catch or a finally, at least one)
try_stmt      = {try} kw lb block (lb catch_clause)+ (lb finally_clause)?
              | {try} kw lb block lb finally_clause
@silent catch_clause = {catch} kw (sp type_literal (sp ',' lb type_literal)*)? lb block
@silent finally_clause = {finally} kw lb block
trap_stmt     = {trap} kw (sp type_literal)? lb block
function_def  = ({function} | {filter} | {workflow}) kw sp fname (sp '(' lb param_list? lb ')')? lb block
fname         = [^ \t\r\n(){{}};|&,"'`]+
flow_stmt     = ({return} | {throw} | {exit}) kw (sp !term_ahead pipeline)?
              | ({break} | {continue}) kw (sp !term_ahead (name | expression))?
@silent term_ahead = (nl | ';' | '}}' | ')' | '#' | !.)
param_block   = (attribute lb)* {param} kw sp '(' lb param_list? lb ')'
param_list    = param_item (lb ',' lb param_item)*
param_item    = (attribute lb)* variable (sp '=' lb expression)?
attribute     = '[' type_name ('(' lb attr_args? lb ')')? ']'
attr_args     = attr_arg (lb ',' lb attr_arg)*
attr_arg      = word_name sp '=' lb expression | expression | word_name
named_block   = ({begin} | {process} | {end} | {dynamicparam}) kw lb block
data_stmt     = {data} kw (sp dash word_name sp argument)? lb block
block         = '{{' script_body '}}'
# (a param(...) block first: statements may follow on its line)
@silent script_body = lb (param_block term?)? statements

# Pipelines: an assignment, or a command or an expression, then commands
pipeline      = assignment | pipe
assignment    = lvalue sp assign_op lb statement
assign_op     = '=' | '+=' | dash '=' | '*=' | '/=' | '%='
lvalue        = (type_literal sp)* postfix_expr
pipe          = head (sp redirection)* (sp '|' lb command)*
@silent head  = command | expression

# Commands
command       = (invocation sp cmd_target | !keyword_ahead !value_start cmd_name) (elem)* (sp end_of_params (elem_after)*)?
              | !keyword_ahead dash_cmd_name (elem)*
# (& and . call what follows; `.` before a value too: .$x, ."p", .(x); `.\x` is a path)
invocation    = '&' | '.' &([ \t] | '$' | '(' | '{{' | sq_open | dq_open)
@silent cmd_target = argument_atom
cmd_name      = !('.' !bw_char) bareword
@silent bw_char = !uni_quote [^ \t\r\n;|&(){{}},"'`$]
# (a command named like a parameter: -x, -r'' (quotes join it); it ends at a
# colon: -q: then :)
dash_cmd_name = !(dash ({not} | {bnot} | {split} | {join}) kw) &(dash dash_word) dash_cmd_word
dash_cmd_word = dash (bw_sq | bw_dq | !':' bw_char)+ ':'?
# (after `--`, every word is an argument: `-x` too)
end_of_params = dash dash kwp
@silent elem_after = sp (redirection | argument_any)
argument_any  = (argument_atom | bareword_any) (sp ',' lb (argument_atom | bareword_any))*
bareword_any  = !'#' !redirect_ahead bw_part+
# (a statement starting with a value is an expression: $x = ..., [T]::M(),
# @{...}, (...), "...", 5, !x, -not x, +x, {...}; a number glued to letters,
# 5t, is a command's name)
@silent value_start = '$' | '@' | '(' | '[' | '{{' | sq_open | dq_open | '!' | number !(sq_open | dq_open) | '+'
                    | dash ({not} | {bnot} | {split} | {join}) kw | dash !dash_word | ','
# (-x is a command's name, -not an operator)
@silent dash_word = [A-Za-z_?\x80-\xff]
@silent keyword_ahead = keyword kws
# (a keyword is one when a blank or ( { ; | follows: `for''` is a name)
@silent kws   = &([ \t\r\n(){{}};|&] | '`' | !.)
@silent elem  = sp (redirection | stop_parsing | parameter | argument)
# (--% then a blank or the line's end: the rest of the line, up to a |, as it is)
stop_parsing  = '--%' &([ \t\r\n|] | !.) verbatim
verbatim      = [^\r\n|]*
# (-name: needs its argument: `-i:` alone is an error)
parameter     = dash pname (':' sp (argument | argument_any) | !':')
pname         = [A-Za-z_?\x80-\xff] (!uni_quote [^ \t\r\n:;|&(){{}},"'`])*
@silent kwp   = &([ \t\r\n;|&(){{}}] | !.)
argument      = argument_atom (sp ',' lb argument_atom)*
@silent argument_atom = sq_string | dq_string | here_sq | here_dq | number !bare_char | postfix_expr_arg | bareword
@silent bare_char = [^ \t\r\n;|&(){{}},]
# (a variable or $(...) followed by more of a word is a word: $x-- is one)
postfix_expr_arg = (variable | subexpr) arg_postfix !bare_char
                 | (splat | array_expr | hashtable | paren | scriptblock) arg_postfix
@silent arg_postfix = (member invoke? | index)*

# Barewords: as PowerShell splits them (quotes inside one join it)
bareword      = !dash_param !(dash dash kwp) !'#' !redirect_ahead !('@' !bw_char) bw_part+
@silent dash_param = dash [A-Za-z_?\x80-\xff]
@silent redirect_ahead = ([*1-6])? '>' | '<'
@silent bw_part = bw_escape | bw_sq | bw_dq | variable | subexpr | bw_text
# (a ` ending the text: a literal `)
bw_escape     = '`' (uchar | !.)
bw_sq         = sq_string
bw_dq         = dq_string
bw_text       = bw_char+ | '$'

# Redirections (at a word's start); `<` is reserved and n>&2 unsupported: errors
redirection   = merging | file_redirect
merging       = [*2-6] '>&1'
file_redirect = [*1-6]? ('>>' | '>') sp argument_atom

# Expressions: what vetter needs is where they end and the commands in them
expression    = unary (sp binop lb unary)*
binop         = dash ({binops}) kw | '..' | '+' | dash !dash | '*' | '/' | '%' | ','
unary         = (prefix sp)* postfix_expr
# (a cast: a type not followed by :: . or [, which make it a value, and
# followed by what it casts: `$a -is [int]` ends with a type, a value)
@silent prefix = '!' | dash ({not} | {bnot} | {split} | {join}) kw | '++' | dash dash | '+' | dash | ','
               | type_literal !('::' | '.' | '[') &(sp postfix_expr)
postfix_expr  = primary postfix_ops
# (a call only after a member: $x.M(1); {a}(b) is wrong)
@silent postfix_ops = (member invoke? | index | '++' | dash dash)*
member        = ('.' | '::') (name_chars | sq_string | dq_string | variable | paren)
invoke        = '(' lb (expression (lb ',' lb expression)*)? lb ')'
index         = '[' lb expression lb ']'
# (a splat, @x, only as a command's argument)
@silent primary = number | sq_string | dq_string | here_sq | here_dq | variable | subexpr
                | array_expr | hashtable | paren | scriptblock | type_literal
number        = ('0' [xX] [0-9a-fA-F]+ | [0-9]+ ('.' [0-9]+)? ([eE] [+-]? [0-9]+)? | '.' [0-9]+)
                [lLdDuUyYnNsS]? ([kKmMgGtTpP] [bB])? kw
paren         = '(' lb statement lb ')'
subexpr       = '$(' statements ')'
array_expr    = '@(' statements ')'
scriptblock   = '{{' script_body '}}'
hashtable     = '@{{' lb (hash_entry (term? lb hash_entry)*)? term? lb '}}'
hash_entry    = (name_chars | sq_string | dq_string | number | paren | variable) sp '=' lb statement
type_literal  = '[' type_name ']'
type_name     = tchar+ ('[' type_name? (',' type_name)* ']')? tchar*
@silent tchar = [A-Za-z0-9_.`+]

# Strings
sq_string     = sq_open (sq_open sq_open | !sq_open uchar)* sq_open
dq_string     = dq_open dq_part* dq_open
@silent dq_part = dq_escape | dq_open dq_open | subexpr | variable | dq_text | '$'
dq_escape     = '`' uchar
dq_text       = (!dq_open [^`$])+
# (the body may be empty: @' then '@ on the next line)
here_sq       = '@' sq_open sp nl (here_sq_body nl)? sq_open '@'
here_sq_body  = (!(nl sq_open '@') uchar)*
here_dq       = '@' dq_open sp nl (here_dq_body nl)? dq_open '@'
here_dq_body  = (!(nl dq_open '@') (subexpr | variable | dq_escape | uchar))*

# Variables
variable      = '$' ('{{' [^}}]* '}}' | (scope ':')? name_chars | [$?^_])
              | '$' name_chars
splat         = '@' name_chars
@silent scope = [A-Za-z_] [A-Za-z0-9_]*
name          = name_chars
name_chars    = (!uni_special [A-Za-z0-9_?\x80-\xff])+
word_name     = [A-Za-z_] [A-Za-z0-9_-]*

# (en dash, em dash, horizontal bar: dashes too; ‘ ’ ‚ ‛ and “ ” „ quotes)
@silent dash  = '-' | '\xe2\x80\x93' | '\xe2\x80\x94' | '\xe2\x80\x95'
@silent sq_open = '\'' | '\xe2\x80\x98' | '\xe2\x80\x99' | '\xe2\x80\x9a' | '\xe2\x80\x9b'
@silent dq_open = '"' | '\xe2\x80\x9c' | '\xe2\x80\x9d' | '\xe2\x80\x9e'
@silent uni_special = '\xe2\x80' [\x93-\x95\x98-\x9b\x9c-\x9e]
@silent uni_quote = '\xe2\x80' [\x98-\x9b\x9c-\x9e]
# (one character, its UTF-8 bytes together)
@silent uchar = [\x00-\x7f] | [\xc0-\xdf] [\x80-\xbf] | [\xe0-\xef] [\x80-\xbf] [\x80-\xbf]
              | [\xf0-\xf7] [\x80-\xbf] [\x80-\xbf] [\x80-\xbf] | [\x80-\xff]
keyword       = ({keywords})
@silent kw    = ![A-Za-z0-9_-]

# Blanks: ` at a line's end continues it, ` and a blank is a blank; <# #>
# comments anywhere
@silent nl    = '\r'? '\n'
# (form feed, vertical tab: \x0c \x0b; no-break space)
@silent sp    = ([ \t\x0c\x0b] | '\xc2\xa0' | '`' nl | '`' [ \t] | block_comment)*
@silent comment = '#' [^\r\n]*
@silent block_comment = '<#' (!'#>' .)* '#>'
@silent lb    = (sp comment? nl)* sp comment?
"""


def _grammar():
    """The template with {keyword} made case-insensitive, {{ }} made { }."""
    subs = {k: _ci(k) for k in KEYWORDS + ["not", "bnot", "split", "join", "file", "parallel"]}
    subs["keywords"] = " | ".join(_ci(k) for k in STATEMENT_KEYWORDS)
    # (longest first: -notmatch before -not...)
    subs["binops"] = " | ".join(_ci(o) for o in sorted(BINARY_OPERATORS, key=len, reverse=True))
    text = re.sub(r"(?<!\{)\{([a-z]+)\}(?!\})", lambda m: subs[m[1]] if m[1] in subs else m[0], GRAMMAR_TEMPLATE)
    return text.replace("{{", "{").replace("}}", "}")


GRAMMAR = _grammar()
