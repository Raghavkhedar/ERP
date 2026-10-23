// The update form's file picker: add files by choosing, dropping or pasting
// a screenshot, and remove them again before sending.
document.addEventListener("alpine:init", () => {
  Alpine.data("updateFiles", () => ({
    names: [],

    add(files) {
      const all = new DataTransfer();
      for (const file of this.$refs.input.files) all.items.add(file);
      for (const file of files) all.items.add(file);
      this.$refs.input.files = all.files;
      this.sync();
    },

    paste(event) {
      const images = [...event.clipboardData.files].filter((file) =>
        file.type.startsWith("image/"),
      );
      if (!images.length) return; // ordinary text: let it paste
      event.preventDefault();
      const stamp = new Date().toTimeString().slice(0, 8).replaceAll(":", "");
      this.add(
        images.map((file, index) => {
          const extension = file.type.split("/")[1] || "png";
          const suffix = images.length > 1 ? `-${index + 1}` : "";
          return new File([file], `screenshot-${stamp}${suffix}.${extension}`, {
            type: file.type,
          });
        }),
      );
    },

    remove(index) {
      const kept = new DataTransfer();
      [...this.$refs.input.files].forEach((file, i) => {
        if (i !== index) kept.items.add(file);
      });
      this.$refs.input.files = kept.files;
      this.sync();
    },

    sync() {
      this.names = [...this.$refs.input.files].map((file) => file.name);
    },
  }));
});
