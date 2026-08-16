%% ---------------------------------------------------------------------------
%%  «Соло» — курс "Буги-вуги" 2.0, урок 5 (Юлия Шишкина)
%%
%%  Нотный материал снят с авторских партитур в C и G (обе сверены между
%%  собой нота в ноту). Правая рука записана в до мажоре; нужная тональность
%%  получается через \transpose в файлах solo-*.ly.
%%  Партия левой руки (буги-бас) для каждой тональности выписана явно,
%%  чтобы бас всегда оставался в удобной октаве — так же, как это сделано
%%  в авторских версиях C и G.
%% ---------------------------------------------------------------------------

\version "2.24.0"

%% Знаки при ключе ставятся внутри форшлагового момента — см. layout.ily
keyInit = { \key c \major }
graceInit = {
  \grace {
    \key c \major
    \once \override Staff.KeySignature.break-align-symbol = #'key-signature
    s8
  }
}

%% ===== ПРАВАЯ РУКА (эталон — до мажор) =====================================

rightC = {
  \set fingeringOrientations = #'(up)
  \tempo "Swing"

  %% 1
  \acciaccatura { \keyInit fis'' } <g'' c'''>8 c'' <f'' a''> c''
  \acciaccatura dis'' <e'' g''> c'' r4
  %% 2
  \acciaccatura fis'' <g''-3 c'''-5>8 c'' <f''-3 a''-5>
  \acciaccatura { dis''-2 } <e''-2 g''-4> r8
  \acciaccatura fis'' <g'' c'''> <g'' c'''> <g'' c'''>
  %% 3
  \acciaccatura fis'' <g''-3 c'''-5>8 c'' <f''-3 a''-5> <ees''-3 g''-5>
  e''-4 c''-2 a'-1 g'-2
  \break
  %% 4
  <bes'-3 e''-5>8 g' <a'-2 e''-5> <g'-1 e''-5> r8
  \acciaccatura fis'' <g'' c'''> <g'' c'''> <g'' c'''>
  %% 5
  \acciaccatura fis'' <g'' c'''>8 c'' <f'' a''> <ees'' g''> ~ <ees'' g''> c'' r4
  %% 6
  \acciaccatura fis'' <g'' c'''>8 c'' <f'' a''> <ees'' g''> ~ <ees'' g''>
  \acciaccatura fis'' <g'' c'''> <g'' c'''> <g'' c'''>
  \break
  %% 7
  \acciaccatura fis'' <g''-3 c'''-5>8 c'' <f''-3 a''-5> <ees''-3 g''-5>
  e''-4 c''-2 a'-1 g'-2
  %% 8
  \acciaccatura fis' <g'-3 bes'-5>8 c' <f'-3 a'-5>
  \acciaccatura { dis'-2 } <e'-2 g'-4> r8
  \acciaccatura fis'' <g'' c'''> <g'' c'''> <g'' c'''>
  %% 9
  <fis'' c'''>8 <g'' c'''> <g'' c'''> <g'' c'''>
  <fis'' c'''> <g'' c'''> <g'' c'''> <g'' c'''>
  \break
  %% 10
  <fis'' c'''>8 <g'' c'''> <g'' c'''> <g'' c'''>
  <fis'' c'''> <g'' c'''> <g'' c'''> <g'' c'''>
  %% 11
  \acciaccatura fis'' <g'' bes''>8 c'' <f'' a''> <ees'' g''>
  e'' c'' a' g'
  %% 12
  <bes'-3 e''-5>8 g' <a'-2 e''-5> <g'-1 e''-5> r2
  \bar "|."
}

%% ===== ЛЕВАЯ РУКА ==========================================================
%% Буги-бас: восемь восьмых в такте, чередование
%% «основной тон + квинта» / «основной тон + секста».
%% Блюзовый квадрат: I I I I | IV IV | I I | V | IV | I I

makeLeft =
#(define-music-function (I IV V) (ly:music? ly:music? ly:music?)
   #{ \graceInit $I $I $I $I $IV $IV $I $I $V $IV $I $I \bar "|." #})

%% --- до мажор (авторский оригинал) ---
lcI   = { <c, g,>8 q <c, a,> q <c, g,> q <c, a,> q }
lcIV  = { <f, c>8  q <f, d>  q <f, c>  q <f, d>  q }
lcV   = { <g, d>8  q <g, e>  q <g, d>  q <g, e>  q }
leftC = \makeLeft \lcI \lcIV \lcV

%% --- соль мажор (авторский оригинал) ---
lgI   = { <g, d>8  q <g, e>  q <g, d>  q <g, e>  q }
lgIV  = { <c, g,>8 q <c, a,> q <c, g,> q <c, a,> q }
lgV   = { <d, a,>8 q <d, b,> q <d, a,> q <d, b,> q }
leftG = \makeLeft \lgI \lgIV \lgV

%% --- фа мажор ---
lfI   = { <f, c>8   q <f, d>   q <f, c>   q <f, d>   q }
lfIV  = { <bes, f>8 q <bes, g> q <bes, f> q <bes, g> q }
lfV   = { <c g>8    q <c a>    q <c g>    q <c a>    q }
leftF = \makeLeft \lfI \lfIV \lfV

%% --- си-бемоль мажор ---
lbI   = { <bes, f>8    q <bes, g> q <bes, f>    q <bes, g> q }
lbIV  = { <ees, bes,>8 q <ees, c> q <ees, bes,> q <ees, c> q }
lbV   = { <f, c>8      q <f, d>   q <f, c>      q <f, d>   q }
leftB = \makeLeft \lbI \lbIV \lbV
