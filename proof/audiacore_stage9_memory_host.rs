use std::{collections::BTreeMap, io, path::{Path, PathBuf}, sync::Mutex};

use audiacore_host::{FileHost, FileReadAuthority, FileWriteAuthority};

#[derive(Default)]
pub struct MemoryFileHost {
    files: Mutex<BTreeMap<PathBuf, Vec<u8>>>,
}

impl MemoryFileHost {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn bytes(&self, path: &Path) -> Option<Vec<u8>> {
        self.files.lock().expect("memory host lock poisoned").get(path).cloned()
    }
}

impl FileHost for MemoryFileHost {
    type Error = io::Error;

    fn read_optional(
        &self,
        _authority: &FileReadAuthority,
        path: &Path,
    ) -> Result<Option<Vec<u8>>, Self::Error> {
        Ok(self.files.lock().expect("memory host lock poisoned").get(path).cloned())
    }

    fn write(
        &self,
        _authority: &FileWriteAuthority,
        path: &Path,
        bytes: &[u8],
    ) -> Result<(), Self::Error> {
        self.files
            .lock()
            .expect("memory host lock poisoned")
            .insert(path.to_path_buf(), bytes.to_vec());
        Ok(())
    }

    fn remove(
        &self,
        _authority: &FileWriteAuthority,
        path: &Path,
    ) -> Result<(), Self::Error> {
        self.files.lock().expect("memory host lock poisoned").remove(path);
        Ok(())
    }
}
