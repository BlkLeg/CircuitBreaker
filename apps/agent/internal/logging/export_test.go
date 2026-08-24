package logging

import (
	"io"
	"log"
)

// useForTest redirects output and pins a level for one test, returning the
// restore function. Test-only, so the production API keeps no writer seam.
func useForTest(w io.Writer, l Level) func() {
	mu.Lock()
	previousOut, previousLevel := out, level
	out, level = w, l
	mu.Unlock()

	previousFlags := log.Flags()
	previousWriter := log.Writer()
	log.SetFlags(0)
	log.SetOutput(gate{})

	return func() {
		mu.Lock()
		out, level = previousOut, previousLevel
		mu.Unlock()
		log.SetFlags(previousFlags)
		log.SetOutput(previousWriter)
	}
}
