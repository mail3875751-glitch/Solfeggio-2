\version "2.24.0"
\include "layout.ily"
\include "solo.ily"

\header {
  title    = \cyr #4 "Соло в F"
  subtitle = \cyr #0 "Курс \"Буги-вуги\" 2.0 Урок 5"
  composer = \cyr #0 "Юлия Шишкина"
  tagline  = ##f
}

%% правая рука — на чистую квинту вниз от до мажора
\score { \makeScore { \transpose c' f \rightC } \leftF \layout { } }
