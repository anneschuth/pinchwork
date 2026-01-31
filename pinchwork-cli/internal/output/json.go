package output

import (
	"encoding/json"
	"fmt"
	"io"
)

func JSON(w io.Writer, v interface{}) error {
	data, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return err
	}
	fmt.Fprintln(w, string(data))
	return nil
}
