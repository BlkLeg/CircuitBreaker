package logging

import (
	"io"
	"log"
)

// useForTest redirects output and pins a level for one test, returning the
// restore function. Test-only, so the production API keeps no writer seam.
func useForTest(w io.Writer, l Level) func() {
	restoreStream := UseWriter(w, l)

	previousFlags := log.Flags()
	previousWriter := log.Writer()
	log.SetFlags(0)
	log.SetOutput(gate{})

	return func() {
		restoreStream()
		log.SetFlags(previousFlags)
		log.SetOutput(previousWriter)
	}
}
