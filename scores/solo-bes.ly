\version "2.24.0"
\include "layout.ily"
\include "solo.ily"

\header {
  title    = \cyr #4 "Соло в B♭"
  subtitle = \cyr #0 "Курс \"Буги-вуги\" 2.0 Урок 5"
  composer = \cyr #0 "Юлия Шишкина"
  tagline  = ##f
}

%% правая рука — на большую секунду вниз от до мажора
\score { \makeScore { \transpose c' bes \rightC } \leftB \layout { } }
