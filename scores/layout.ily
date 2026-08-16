%% Общее оформление для всех тональностей.
%% Формат Letter, размер нотоносца и поля приближены к авторским
%% партитурам (MuseScore, Letter, 12 тактов в четыре строки).

\version "2.24.0"

#(set-global-staff-size 20)

\paper {
  #(set-paper-size "letter")
  top-margin = 14\mm
  bottom-margin = 14\mm
  left-margin = 16\mm
  right-margin = 16\mm
  markup-system-spacing.padding = #5
  system-system-spacing.basic-distance = #17
  print-page-number = ##f
}

%% Заголовки — шрифтом с кириллицей
cyr =
#(define-scheme-function (size str) (number? string?)
   #{ \markup \override #'(font-name . "DejaVu Sans") \fontsize #size #str #})

%% Пьеса начинается с форшлага, то есть с момента «до первой доли».
%% Если ключ/тональность задавать обычным способом, LilyPond успевает
%% напечатать умолчания (скрипичный ключ и 4/4) ещё до форшлага, а затем
%% печатает их второй раз. Поэтому бас-ключ задаётся при создании контекста,
%% а знаки при ключе выставляются внутри форшлагового момента.
makeScore =
#(define-music-function (rh lh) (ly:music? ly:music?)
   #{
     \new PianoStaff <<
       \new Staff { $rh }
       \new Staff \with {
         clefGlyph = "clefs.F"
         clefPosition = #2
         middleCClefPosition = #6
         middleCPosition = #6
       } { $lh }
     >>
   #})
