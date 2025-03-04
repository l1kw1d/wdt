/**
 * Copyright (c) 2014-present, Facebook, Inc.
 * All rights reserved.
 *
 * This source code is licensed under the BSD-style license found in the
 * LICENSE file in the root directory of this source tree. An additional grant
 * of patent rights can be found in the PATENTS file in the same directory.
 */
#include <wdt/util/FileByteSource.h>

#include <algorithm>
#include <fcntl.h>
#include <glog/logging.h>
#include <sys/types.h>
#include <sys/stat.h>
namespace facebook {
namespace wdt {

int FileUtil::openForRead(ThreadCtx &threadCtx, const std::string &filename,
                          bool isDirectReads) {
  int openFlags = O_RDONLY;
  if (isDirectReads) {
#ifdef O_DIRECT
    // no need to change any flags if we are using F_NOCACHE
    openFlags |= O_DIRECT;
#endif
  }
  int fd;
  {
    PerfStatCollector statCollector(threadCtx, PerfStatReport::FILE_OPEN);
    fd = ::open(filename.c_str(), openFlags);
  }
  if (fd >= 0) {
    if (isDirectReads) {
#ifndef O_DIRECT
#ifdef F_NOCACHE
      VLOG(1) << "O_DIRECT not found, using F_NOCACHE instead "
              << "for " << filename;
      int ret = fcntl(fd, F_NOCACHE, 1);
      if (ret) {
        PLOG(ERROR) << "Not able to set F_NOCACHE";
      }
#else
      WDT_CHECK(false)
          << "Direct read enabled, but both O_DIRECT and F_NOCACHE not defined "
          << filename;
#endif
#endif
    }
  } else {
    PLOG(ERROR) << "Error opening file " << filename;
  }
  return fd;
}

FileByteSource::FileByteSource(SourceMetaData *metadata, int64_t size,
                               int64_t offset)
    : metadata_(metadata),
      size_(size),
      offset_(offset),
      bytesRead_(0),
      alignedReadNeeded_(false) {
  transferStats_.setId(getIdentifier());
}

ErrorCode FileByteSource::open(ThreadCtx *threadCtx) {
  if (metadata_->allocationStatus == TO_BE_DELETED) {
    return OK;
  }
  bytesRead_ = 0;
  this->close();
  threadCtx_ = threadCtx;
  ErrorCode errCode = OK;
  bool isDirectReads = metadata_->directReads;
  VLOG(1) << "Reading in direct mode " << isDirectReads;
  if (isDirectReads) {
#ifdef O_DIRECT
    alignedReadNeeded_ = true;
#endif
  }

  if (metadata_->fd >= 0) {
    VLOG(1) << "metadata already has fd, no need to open " << getIdentifier();
    fd_ = metadata_->fd;
  } else {
    fd_ =
        FileUtil::openForRead(*threadCtx_, metadata_->fullPath, isDirectReads);
    if (fd_ < 0) {
      errCode = BYTE_SOURCE_READ_ERROR;
    }
  }

  transferStats_.setLocalErrorCode(errCode);
  return errCode;
}

void FileByteSource::advanceOffset(int64_t numBytes) {
  offset_ += numBytes;
  size_ -= numBytes;
}

char *FileByteSource::read(int64_t &size) {
  size = 0;
  if (hasError() || finished()) {
    return nullptr;
  }
  const Buffer *buffer = threadCtx_->getBuffer();
  int64_t offsetRemainder = 0;
  if (alignedReadNeeded_) {
    offsetRemainder = (offset_ + bytesRead_) % kDiskBlockSize;
  }
  int64_t logicalRead = (int64_t)std::min<int64_t>(
      buffer->getSize() - offsetRemainder, size_ - bytesRead_);
  int64_t physicalRead = logicalRead;
  if (alignedReadNeeded_) {
    physicalRead = ((logicalRead + offsetRemainder + kDiskBlockSize - 1) /
                    kDiskBlockSize) *
                   kDiskBlockSize;
  }
  const int64_t seekPos = (offset_ + bytesRead_) - offsetRemainder;
  int numRead;
  {
    PerfStatCollector statCollector(*threadCtx_, PerfStatReport::FILE_READ);
    numRead = ::pread(fd_, buffer->getData(), physicalRead, seekPos);
  }
  if (numRead < 0) {
    PLOG(ERROR) << "Failure while reading file " << metadata_->fullPath
                << " need align " << alignedReadNeeded_ << " physicalRead "
                << physicalRead << " offset " << offset_ << " seepPos "
                << seekPos << " offsetRemainder " << offsetRemainder
                << " bytesRead " << bytesRead_;
    this->close();
    transferStats_.setLocalErrorCode(BYTE_SOURCE_READ_ERROR);
    return nullptr;
  }
  if (numRead == 0) {
    LOG(ERROR) << "Unexpected EOF on " << metadata_->fullPath << " need align "
               << alignedReadNeeded_ << " physicalRead " << physicalRead
               << " offset " << offset_ << " seepPos " << seekPos
               << " offsetRemainder " << offsetRemainder << " bytesRead "
               << bytesRead_;
    this->close();
    return nullptr;
  }
  // Can only happen in case of O_DIRECT and when
  // we are trying to read the last chunk of file
  // or we are reading in multiples of disk block size
  // from a sub block of the file smaller than disk block
  // size
  size = numRead - offsetRemainder;
  if (size > logicalRead) {
    WDT_CHECK(alignedReadNeeded_);
    size = logicalRead;
  }
  bytesRead_ += size;
  VLOG(1) << "Size " << size << " need align " << alignedReadNeeded_
          << " physicalRead " << physicalRead << " offset " << offset_
          << " seepPos " << seekPos << " offsetRemainder " << offsetRemainder
          << " bytesRead " << bytesRead_;
  return buffer->getData() + offsetRemainder;
}
}
}
