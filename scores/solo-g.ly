\version "2.24.0"
\include "layout.ily"
\include "solo.ily"

\header {
  title    = \cyr #4 "Соло в G"
  subtitle = \cyr #0 "Курс \"Буги-вуги\" 2.0 Урок 5"
  composer = \cyr #0 "Юлия Шишкина"
  tagline  = ##f
}

%% правая рука — на кварту вниз от до мажора (как в авторской версии)
\score { \makeScore { \transpose c' g \rightC } \leftG \layout { } }
